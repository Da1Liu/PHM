// Phase 1 domain markers. These helpers attach metadata to Express handlers
// without changing request behavior.
export const ApiDomain = Object.freeze({
  EDGE: 'Edge',
  CLOUD: 'Cloud',
  SHARED: 'Shared',
});

export function markApi(domain, purpose, handler) {
  handler.apiDomain = domain;
  handler.apiPurpose = purpose || '';
  return handler;
}

export const edgeApi = (purpose, handler) => markApi(ApiDomain.EDGE, purpose, handler);
export const cloudApi = (purpose, handler) => markApi(ApiDomain.CLOUD, purpose, handler);
export const sharedApi = (purpose, handler) => markApi(ApiDomain.SHARED, purpose, handler);

