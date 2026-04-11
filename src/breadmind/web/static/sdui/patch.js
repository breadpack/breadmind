// src/breadmind/web/static/sdui/patch.js
// Minimal RFC 6902 subset: add, remove, replace. Sufficient for jsonpatch output.
export function applyPatch(doc, patch) {
  let current = JSON.parse(JSON.stringify(doc));
  for (const op of patch) {
    current = applyOp(current, op);
  }
  return current;
}

function applyOp(doc, op) {
  const path = op.path.split('/').slice(1).map(decode);
  if (path.length === 0) {
    // Root replacement
    if (op.op === 'replace' || op.op === 'add') return op.value;
    return doc;
  }
  const last = path.pop();
  let parent = doc;
  for (const seg of path) {
    if (Array.isArray(parent)) {
      parent = parent[Number(seg)];
    } else {
      parent = parent[seg];
    }
  }
  if (op.op === 'add' || op.op === 'replace') {
    if (Array.isArray(parent)) {
      if (last === '-') {
        parent.push(op.value);
      } else {
        const idx = Number(last);
        if (op.op === 'add') {
          parent.splice(idx, 0, op.value);
        } else {
          parent[idx] = op.value;
        }
      }
    } else {
      parent[last] = op.value;
    }
  } else if (op.op === 'remove') {
    if (Array.isArray(parent)) {
      parent.splice(Number(last), 1);
    } else {
      delete parent[last];
    }
  }
  return doc;
}

function decode(s) {
  return s.replace(/~1/g, '/').replace(/~0/g, '~');
}
