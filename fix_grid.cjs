const fs = require('fs');
const glob = require('glob');

const files = [
  'src/pages/AIAlphaScreener.tsx',
  'src/pages/AutopilotPage.tsx',
  'src/pages/BinanceDashboard.tsx',
  'src/pages/ClientOptionsHub.tsx',
  'src/pages/OptionsExpertPage.tsx'
];

files.forEach(file => {
  let content = fs.readFileSync(file, 'utf8');

  // Fix ClientOptionsHub media query in style
  if (file.includes('ClientOptionsHub')) {
    content = content.replace(/style={{ display: "flex", flexDirection: "column", gap: 24, '@media \(min-width: 1024px\)': { flexDirection: "row" } as any }}/g, 
      `style={{ display: "flex", gap: 24, flexWrap: "wrap" }}`);
  }

  // Regex to match <Grid ...> with item, xs, sm, md, lg, xl
  // We'll just replace `<Grid item xs={12} md={6}>` and `<Grid xs={12} md={6}>`
  // with `<Grid size={{ xs: 12, md: 6 }}>`
  
  // This loop iteratively replaces them
  let changed = true;
  while (changed) {
    const orig = content;
    content = content.replace(/<Grid(?:\s+item)?((?:\s+(?:xs|sm|md|lg|xl)=\{[^\}]+\})+)([^>]*)>/, (match, props, rest) => {
      // parse props
      const sizeObj = {};
      const propRegex = /(xs|sm|md|lg|xl)=\{([^\}]+)\}/g;
      let p;
      while ((p = propRegex.exec(props)) !== null) {
        sizeObj[p[1]] = p[2];
      }
      const sizeStr = Object.keys(sizeObj).map(k => `${k}: ${sizeObj[k]}`).join(', ');
      return `<Grid size={{ ${sizeStr} }}${rest}>`;
    });
    if (orig === content) changed = false;
  }

  fs.writeFileSync(file, content);
});
