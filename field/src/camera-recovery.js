export async function persistCameraResult(store, context, result) {
  if (!context || !result?.base64String || !['jpeg', 'jpg', 'png'].includes(result.format))
    throw new Error('LOCAL_CAPTURE_RESULT_INVALID');
  const original = Uint8Array.from(atob(result.base64String), letter => letter.charCodeAt(0));
  await store.completeCameraCapture(context, original,
    result.format === 'png' ? 'image/png' : 'image/jpeg');
  return context.media_id;
}

export async function recoverRestoredCamera(store, event) {
  if (event.pluginId !== 'Camera' || event.methodName !== 'getPhoto') return null;
  const context = await store.pendingCameraCapture();
  if (!context) return null;
  if (!event.success) {
    await store.cancelCameraCapture(context);
    return null;
  }
  return {context, mediaId: await persistCameraResult(store, context, event.data)};
}
