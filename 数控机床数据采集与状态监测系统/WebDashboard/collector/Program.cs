using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using MachineCollector;

// 鏃犵晫闈?NI 鎸姩閲囬泦銆愬畧鎶よ繘绋嬨€戯細甯搁┗杩愯锛岀洃鍚?DB phm_v2.acq_config.data.control.ni_run銆?// Web 绔€屽紑濮?鍋滄閲囬泦銆嶅彧鏀硅繖寮犺〃鐨勬爣蹇楋紝鏈繘绋嬫嵁姝ゅ惎鍋?NI 閲囬泦锛涚姸鎬?蹇冭烦鍥炲啓琛ㄣ€?// 钀界洏璧?鐗瑰緛+浜嬩欢/鎵嬪姩鍘熷鍧?绛栫暐锛堣 VibStore锛夛紝涓嶅啀鍐欎竴閲囨牱鐐逛竴琛岀殑澶ц〃銆?// NI 璇婚敊璇紙濡傛嫈 USB锛夆啋 鑷仠 + 娓呮爣蹇楋紝閬垮厤鍍靛案銆侽PC UA 鐢?node 鍚庣璐熻矗锛屼簰涓嶅奖鍝嶃€?
string cfgPath = Path.Combine(AppContext.BaseDirectory, "appsettings.json");
var settings = JsonConvert.DeserializeObject<AppSettings>(File.ReadAllText(cfgPath)) ?? new AppSettings();
var db = settings.Database;

var envPwd = Environment.GetEnvironmentVariable("COLLECTOR_PGPASSWORD");
if (!string.IsNullOrEmpty(envPwd)) db.Password = envPwd;

var control = new CollectorControl(db);
var store = new VibStore(db);
try
{
    control.Ensure();
    store.EnsureTables();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"鍒濆鍖栧け璐ワ紙妫€鏌?DB 杩炴帴/瀵嗙爜锛? {ex.Message}");
    return 2;
}

Console.WriteLine($"閲囬泦瀹堟姢杩涚▼宸插惎鍔?@ {db.Host}:{db.Port}/{db.Database}");
Console.WriteLine("绛夊緟 Web 绔€屽紑濮嬮噰闆嗐€嶆寚浠わ紙phm_v2.acq_config.data.control.ni_run锛夈€侰trl+C 閫€鍑恒€?);

using var cts = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cts.Cancel(); };

// 鈥斺€?閲囬泦浼氳瘽鐘舵€侊紙浠呬富寰幆绾跨▼璇诲啓 acquiring锛宲rocessor 璇?volatile 瀛楁锛夆€斺€?Acquisition? current = null;
string? faultMsg = null;
int lastCaptureSeen = 0;
var sw = Stopwatch.StartNew();
long lastSamples = 0;

while (!cts.IsCancellationRequested)
{
    CollectorControl.Command cmd;
    try { cmd = control.ReadCommand(); }
    catch (Exception ex) { Console.Error.WriteLine($"璇诲懡浠ゅけ璐? {ex.Message}"); SleepStep(); continue; }

    // 鏁呴殰鑷仠锛堜繚鐣?faultMsg锛屼娇 Web 绔湅寰楀埌鍋滄鍘熷洜锛岀洿鍒颁笅娆℃垚鍔熷惎鍔級
    if (current != null && current.Fault != null)
    {
        faultMsg = current.Fault;
        Console.Error.WriteLine($"閲囬泦鏁呴殰锛岃嚜鍔ㄥ仠姝? {faultMsg}");
        current.Stop();
        current = null;
        // 涓嶆竻 ni_run锛氫繚鐣欓敊璇€佽 Web 鐪嬭锛岀敤鎴风偣銆屽仠姝€嶆墠澶嶄綅锛堣涓嬫柟 !cmd.NiRun 鍒嗘敮锛夈€?    }

    if (cmd.NiRun && current == null && faultMsg == null)
    {
        try
        {
            current = StartAcquisition(db, store, out string session);
            lastCaptureSeen = cmd.CaptureSeq; // 鍚姩鐬棿鐨勬姄鍙栬姹備笉琛ラ噰
            sw.Restart(); lastSamples = 0;
            Console.WriteLine($"鈻?寮€濮嬮噰闆?session={session} ({current.Description})");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"鍚姩閲囬泦澶辫触: {ex.Message}");
            current = null; faultMsg = ex.Message;
        }
    }
    else if (cmd.NiRun && faultMsg != null)
    {
        // 涓婃鍑洪敊鍚?Web 鍙堢疆浣嶄簡 ni_run锛熻繖閲屼笉鑷姩閲嶅惎锛氭竻閿欒闇€鍏堝仠鍐嶅紑銆?        // 鐢ㄦ埛鍦?Web 鐐广€屽仠姝€嶄細鎶?ni_run 澶嶄綅锛屼粠鑰屾竻闄?faultMsg锛堣涓嬫柟锛夈€?    }
    else if (!cmd.NiRun)
    {
        if (current != null)
        {
            Console.WriteLine("鈻?鍋滄閲囬泦");
            current.Stop();
            current = null;
        }
        faultMsg = null; // 鍋滄鍗虫竻闄ら敊璇€侊紝鍏佽涓嬫鍚姩
    }

    // 蹇冭烦锛堟瘡涓?tick 閮藉啓锛屼娇 Web 绔?daemonAlive 濮嬬粓涓虹湡锛?    if (current != null)
    {
        if (cmd.CaptureSeq != lastCaptureSeen)
        {
            current.RequestCapture(cmd.CaptureSeq);
            lastCaptureSeen = cmd.CaptureSeq;
            Console.WriteLine($"馃摳 鏀跺埌鎶撳彇璇锋眰 #{cmd.CaptureSeq}");
        }
        long now = current.SamplesProcessed;
        double sps = (now - lastSamples) / Math.Max(0.001, sw.Elapsed.TotalSeconds);
        lastSamples = now; sw.Restart();
        try { control.Heartbeat("running", "", now, sps, current.Session, current.CaptureDone); } catch { }
    }
    else
    {
        try { control.Heartbeat(faultMsg != null ? "error" : "idle", faultMsg ?? "", 0, 0, null, lastCaptureSeen); } catch { }
    }

    SleepStep();
}

Console.WriteLine("瀹堟姢杩涚▼閫€鍑衡€?);
current?.Stop();
try { control.Heartbeat("idle", "杩涚▼閫€鍑?, 0, 0, null, lastCaptureSeen); } catch { }
return 0;

void SleepStep()
{
    try { Task.Delay(500, cts.Token).Wait(); } catch { }
}

// 鍒涘缓骞跺惎鍔ㄤ竴娆￠噰闆嗕細璇濓紙璇?DB 閲囬泦閰嶇疆 鈫?寤烘簮 鈫?璧风壒寰?鍘熷澶勭悊绠＄嚎锛?static Acquisition StartAcquisition(DatabaseOptions db, VibStore store, out string session)
{
    var acq = ConfigStore.TryLoadAcquisition(db);
    if (acq == null || acq.ChannelCount == 0)
        throw new InvalidOperationException("閲囬泦閰嶇疆缂哄け锛氳鍦?Web 閰嶇疆椤佃缃€氶亾锛坅pp_config.acquisition锛?);

    session = $"{acq.TableBaseName}_{DateTime.Now:yyyyMMdd_HHmmss}";
    var a = new Acquisition(acq, store, session);
    a.Start();
    return a;
}
