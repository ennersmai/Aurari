const fs = require('fs');
const path = require('path');
const base = path.join(process.cwd(), 'node_modules', '@pixiv', 'three-vrm');
function find(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) {
      find(p);
    } else if (/\.d\.ts$/.test(e.name)) {
      const txt = fs.readFileSync(p, 'utf8');
      if (/VRMLoaderPlugin|VRMAnimation|lookAt|MToonMaterialLoaderPlugin|VRMUtils/.test(txt)) {
        console.log(p);
      }
    }
  }
}
find(base);
