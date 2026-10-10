export function prepareMainSource(source) {
  return source.replace(/^import[\s\S]*?;\r?\n/gm, '');
}
