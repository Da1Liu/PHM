# app.py
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_sock import Sock
import threading
import json
import time
import requests
import os
from datetime import datetime
import pandas as pd
import numpy as np 
import sys # 用于更健壮的异常处理

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# Global variables
collection_thread = None
is_collecting = False
websocket_client = None
raw_data_file_path = None
collection_start_time = 0
collection_count = 0
data_cached = False

# Global storage for export configuration (sent by frontend)
export_config = {}

# Mapping for brief register names
brief_reg_map = {
    '/MACHINE/CONTROLLER/VARIABLE@REG_D': 'D',
    '/MACHINE/CONTROLLER/VARIABLE@REG_X': 'X',
    '/MACHINE/CONTROLLER/VARIABLE@REG_Y': 'Y',
    '/MACHINE/CONTROLLER/VARIABLE@REG_F': 'F',
    '/MACHINE/CONTROLLER/VARIABLE@REG_G': 'G',
    '/MACHINE/CONTROLLER/VARIABLE@REG_R': 'R',
    '/MACHINE/CONTROLLER/VARIABLE@REG_W': 'W',
    '/MACHINE/CONTROLLER/VARIABLE@REG_B': 'B',
    '/MACHINE/CONTROLLER/VARIABLE@REG_I': 'I',
    '/MACHINE/CONTROLLER/VARIABLE@REG_Q': 'Q',
    '/MACHINE/CONTROLLER/VARIABLE@REG_K': 'K',
    '/MACHINE/CONTROLLER/VARIABLE@REG_T': 'T',
    '/MACHINE/CONTROLLER/VARIABLE@REG_C': 'C',
    '/MACHINE/CONTROLLER/VARIABLE@CHAN_0': 'CH0',
    '/MACHINE/CONTROLLER/VARIABLE@AXIS_0': 'AX0',
    '/MACHINE/CONTROLLER/VARIABLE@AXIS_1': 'AX1',
    '/MACHINE/CONTROLLER/VARIABLE@AXIS_2': 'AX2',
    '/MACHINE/CONTROLLER/VARIABLE@AXIS_5': 'AX5'
}

def get_brief_name(item):
    """Generates a brief name for a register item."""
    path = item['path']
    index = item['index']
    prefix = brief_reg_map.get(path, 'Unknown')
    return f"{prefix}_{index}" if 'AXIS' in path or 'CHAN' in path else f"{prefix}{index}"

def flatten_list(nested_list):
    """Flattens a potentially nested list (compatible with Python < 3.10)"""
    if not isinstance(nested_list, list):
        return [nested_list]
    
    flattened = []
    for element in nested_list:
        if isinstance(element, list):
            flattened.extend(flatten_list(element))
        else:
            flattened.append(element)
    return flattened

def collect_data_task(config):
    """
    Data collection task
    :param config: Collection configuration
    """
    global is_collecting, raw_data_file_path, collection_count, collection_start_time, data_cached, websocket_client

    # 确保在线程启动时 is_collecting 为 True
    if not is_collecting:
        print("Collector thread started but global flag is False. Exiting.")
        return

    try:
        api_url = f"http://{config['api_client_address']}:19001/v1/{config['machine_serial']}/data/"
        
        request_body = {
            "operation": "get_value",
            "items": config['registers']
        }
        
        brief_names = []
        for item in config['registers']:
            path = item['path']
            indices = item['index']
            if isinstance(indices, list):
                for index in indices:
                    brief_names.append(get_brief_name({'path': path, 'index': index}))
            else:
                brief_names.append(get_brief_name({'path': path, 'index': indices}))

        # Set up the file path and write the header
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        raw_data_file_path = os.path.join("data", f"raw_collection_{timestamp}.txt")
        os.makedirs(os.path.dirname(raw_data_file_path), exist_ok=True)
        
        # 使用 'a' 模式确保文件不存在时创建，存在时追加（但我们这里每次都创建新文件）
        with open(raw_data_file_path, "a") as f:
            plan_info = ""
            if config['mode'] == 'time':
                plan_info = f"mode=time, total={config['total_time']}s, interval={config['interval']}ms"
            else:
                plan_info = f"mode=points, total={config['total_points']} points, interval={config['interval']}ms"
            
            f.write(f"# Plan: {plan_info}\n")
            f.write(f"# Headers: {','.join(brief_names)}\n")
            
        collection_start_time = time.time()
        collection_count = 0
        data_cached = False

        while is_collecting:
            try:
                # 尝试进行API请求
                response = requests.post(api_url, json=request_body, timeout=10)
                response.raise_for_status() # 抛出 HTTP 错误，如 4xx/5xx
                data = response.json()

                if data.get("status") == "SUCCESS":
                    # Write data to the raw data file
                    with open(raw_data_file_path, "a") as f:
                        f.write(f"{datetime.now().isoformat()},{json.dumps(data)}\n")
                    
                    data_cached = True
                    
                    # Push real-time data to the frontend
                    try:
                        if websocket_client:
                            # 检查 websocket_client.connected 属性，更健壮
                            if websocket_client.connected: 
                                websocket_client.send(json.dumps(data))
                    except Exception as e:
                        print(f"WebSocket send error (client likely disconnected): {e}")
                        # 不将 is_collecting 设为 False，只断开WS不影响采集
                        
                    collection_count += 1
                    
                    # Check collection termination conditions
                    if config['mode'] == 'points' and collection_count >= config['total_points']:
                        print("Collection finished: Reached total points.")
                        is_collecting = False
                    elif config['mode'] == 'time' and (time.time() - collection_start_time) >= config['total_time']:
                        print("Collection finished: Reached total time.")
                        is_collecting = False

            except requests.exceptions.RequestException as e:
                # HTTP 或网络错误
                print(f"--- Fatal Network Error: {e}. Stopping collection. ---")
                is_collecting = False
            except Exception as e:
                 # 捕获其他意外错误
                print(f"--- Unexpected Error in Collection Loop: {e}. Stopping collection. ---")
                is_collecting = False
                
            # Sleep for the interval
            if is_collecting:
                time.sleep(config['interval'] / 1000)

    except Exception as e:
        print(f"--- Major Collection Task Error: {e} ---")
    finally:
        # 无论如何，确保采集状态被标记为停止，并记录实际结果
        is_collecting = False
        print("Collection task cleanup started.")
        
        actual_total_time = time.time() - collection_start_time
        # Final comment line with actual results
        if raw_data_file_path and os.path.exists(raw_data_file_path):
            try:
                with open(raw_data_file_path, "a") as f:
                    f.write(f"# Actual: total_points={collection_count}, total_time={actual_total_time:.2f}s\n")
            except Exception as e:
                print(f"Error writing final comment to file: {e}")
        
        # Send final stop message to frontend
        if websocket_client:
            try:
                if websocket_client.connected:
                    websocket_client.send(json.dumps({"status": "COLLECTION_STOPPED"}))
            except:
                pass
        print("Collection task finished.")

@app.route('/api/start-collection', methods=['POST'])
def start_collection():
    """Start data collection"""
    global is_collecting, collection_thread, data_cached

    if is_collecting:
        return jsonify({"status": "error", "message": "Already collecting data"}), 409

    config = request.json
    
    if not all(k in config for k in ["api_client_address", "machine_serial", "interval", "mode", "registers"]):
        return jsonify({"status": "error", "message": "Invalid configuration"}), 400
    
    if not config['registers']:
        return jsonify({"status": "error", "message": "Please add registers to query before starting collection."}), 400

    is_collecting = True
    data_cached = False
    collection_thread = threading.Thread(target=collect_data_task, args=(config,))
    # 将线程标记为守护线程，确保主程序退出时它也会退出
    collection_thread.daemon = True 
    collection_thread.start()

    return jsonify({"status": "success", "message": "Collection started"})

@app.route('/api/stop-collection', methods=['POST'])
def stop_collection():
    """Stop data collection by setting the flag"""
    global is_collecting
    if is_collecting:
        # 设置停止标志，让采集线程优雅退出
        is_collecting = False 
    return jsonify({"status": "success", "message": "Stop signal sent."})

@app.route('/api/export-data-config', methods=['POST'])
def save_export_config():
    """Save the export configuration (formulas, MA windows) from the frontend."""
    global export_config
    try:
        data = request.json
        if not data.get('register_configs'):
            return jsonify({"status": "error", "message": "Missing register_configs in payload"}), 400
        export_config = data
        return jsonify({"status": "success", "message": "Export configuration saved."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to save config: {e}"}), 500

def safe_eval(expression, variable_map):
    """Custom safe evaluation function to execute formulas."""
    
    # 替换变量名
    temp_expression = expression
    for brief_name, value in variable_map.items():
        # 确保只替换完整的变量名
        # 将 NaN 替换为字符串 "float('nan')" 以便在 eval 中正确处理
        str_value = str(value) if not pd.isna(value) else 'float("nan")'
        temp_expression = temp_expression.replace(brief_name, str_value)
        
    try:
        # 使用 eval() 仅在内部环境中进行，并假设用户只会输入数学表达式
        result = eval(temp_expression)
        return float(result)
    except Exception:
        return np.nan # 运算失败返回 NaN

def process_and_export_data():
    """Processes raw data with config and exports to CSV."""
    global raw_data_file_path, export_config

    if not raw_data_file_path or not os.path.exists(raw_data_file_path):
        return None, "No raw data file found."

    if not export_config or not export_config.get('register_configs'):
        return None, "No export configuration received from frontend."

    # 1. Read Raw Data and Comments
    timestamps = []
    values_list = []
    
    plan_comment = ""
    actual_comment = ""
    brief_headers = []
    
    try:
        with open(raw_data_file_path, 'r') as f:
            for line in f:
                if line.startswith('# Plan:'):
                    plan_comment = line.strip()
                elif line.startswith('# Actual:'):
                    actual_comment = line.strip()
                elif line.startswith('# Headers:'):
                    # Extract original brief headers from raw data file
                    brief_headers = [h.strip() for h in line.replace('# Headers:', '').strip().split(',')]
                elif not line.startswith('#'):
                    # Data line format: timestamp,{"status": "SUCCESS", "value": [value1, value2, ...]}
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        timestamps.append(parts[0])
                        try:
                            data = json.loads(parts[1])
                            # 使用兼容低版本的展平函数
                            raw_values = flatten_list(data.get('value', []))
                            values_list.append(raw_values)
                        except json.JSONDecodeError:
                            # 捕获 JSON 解码错误，记录为空列表
                            values_list.append([]) 
    except Exception as e:
        # 捕获文件读取过程中的错误
        return None, f"Error reading raw data file: {e}"

    if not values_list or not brief_headers:
        return None, "Raw data file is empty or headers are missing."
    
    # 2. Convert to DataFrame for processing
    max_len = max(len(v) for v in values_list) if values_list else 0
    values_list_padded = [v + [np.nan] * (max_len - len(v)) for v in values_list]

    df_raw = pd.DataFrame(values_list_padded, columns=brief_headers)
    df_processed = pd.DataFrame({'Timestamp': timestamps})
    
    # 3. Apply formulas and MA
    
    formula_comments = []
    
    for key, config in export_config['register_configs'].items():
        brief_name = config['brief_name']
        formula = config['formula'].strip()
        ma_window = int(config['maWindow'])
        
        # 验证原始数据中是否存在该列，防止 KeyError
        if brief_name not in df_raw.columns:
            print(f"Warning: Register {brief_name} not found in raw data columns. Skipping.")
            continue # 跳过不存在的寄存器

        # A) Apply Formula if present
        if formula:
            formula_label = f"{brief_name} (Calculated)"
            formula_comments.append(f"{brief_name}={formula}")

            # Apply the formula across the entire DataFrame row by row
            df_processed[formula_label] = df_raw.apply(
                lambda row: safe_eval(formula, {col: row[col] for col in df_raw.columns}), 
                axis=1
            )
            series_to_process = df_processed[formula_label]
        else:
            # 直接使用原始数据系列
            series_to_process = df_raw[brief_name]
            formula_label = brief_name

        # B) Apply Moving Average (MA) if present
        if ma_window > 0:
            ma_label = f"{formula_label}_MA{ma_window}"
            
            # 使用 pandas 的 rolling().mean() 计算滑动平均
            # min_periods=1 确保一开始就能有数据，即使窗口未满
            df_processed[ma_label] = series_to_process.rolling(window=ma_window, min_periods=1).mean()
            
            # 最终导出的列是 MA 列
            df_processed[brief_name] = df_processed[ma_label] 
        else:
            # 最终导出的列是公式处理或原始数据列
            df_processed[brief_name] = series_to_process

    # 4. Prepare Final Output File

    # 构建最终的列顺序：Timestamp + 所有 brief names
    final_columns = ['Timestamp'] + [config['brief_name'] for config in export_config['register_configs'].values() if config['brief_name'] in df_processed.columns]
    df_final = df_processed[final_columns]
    
    # Add formula comments to the header metadata
    formula_comment_line = f"# Formulas: {'; '.join(formula_comments)}\n" if formula_comments else ""
    
    # Create temp CSV file
    temp_csv_path = os.path.join("data", f"export_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    
    # Write metadata comments first
    metadata = f"{plan_comment}\n{actual_comment}\n{formula_comment_line}"
    
    try:
        with open(temp_csv_path, 'w', encoding='utf-8') as f:
            f.write(metadata)
            
        # Append the DataFrame content, **设置小数点精度为 3 位**
        df_final.to_csv(temp_csv_path, index=False, mode='a', float_format='%.3f')
        
        return temp_csv_path, None
    except Exception as e:
        return None, f"Error writing final CSV file: {e}"


@app.route('/api/export-data', methods=['GET'])
def export_data():
    """Export the collected data as CSV/Excel."""
    global data_cached, raw_data_file_path, export_config

    if not data_cached or not raw_data_file_path or not os.path.exists(raw_data_file_path):
        return jsonify({"status": "error", "message": "No data available to export. Please start a collection first."}), 404
    
    if not export_config or not export_config.get('register_configs'):
        return jsonify({"status": "error", "message": "Export configuration missing. Please click '更新列表' and then '导出数据'."}), 400

    csv_path, error = process_and_export_data()

    if error:
        return jsonify({"status": "error", "message": f"Data processing failed: {error}"}), 500

    # Determine filename
    base_name = os.path.basename(raw_data_file_path).replace('raw_collection_', 'processed_').replace('.txt', '.csv')
    
    return send_file(
        csv_path,
        as_attachment=True,
        download_name=base_name,
        mimetype='text/csv'
    )

@sock.route('/data-stream')
def data_stream(ws):
    """WebSocket real-time data stream"""
    global websocket_client
    websocket_client = ws
    print("WebSocket client connected.")
    try:
        while ws.connected:
            time.sleep(1)
    except:
        pass
    finally:
        print("WebSocket client disconnected.")
        websocket_client = None

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000)