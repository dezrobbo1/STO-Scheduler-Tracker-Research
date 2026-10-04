export async function resumeDraftWithNotice(store, identity, id, notice, onLoaded) {
  try {
    if (!identity) throw new Error('Sign in to access this photo.');
    const current = await store.media(identity.actor, identity.project, id);
    if (!current) throw new Error('LOCAL_MEDIA_UNKNOWN');
    await onLoaded(current);
    return true;
  } catch (error) {
    notice(`Photo cannot be resumed: ${error.message}`);
    return false;
  }
}

export function clearProtectedPreview(canvas, annotation) {
  canvas.width = 0;
  canvas.height = 0;
  annotation.hidden = true;
}

export async function readSelectedPhoto(file, originatingIdentity, currentIdentity) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  return currentIdentity() === originatingIdentity ? bytes : null;
}
