const COMMANDS: Record<string, string> = {
  longrightarrow: '→',
  rightarrow: '→',
  longleftarrow: '←',
  leftarrow: '←',
  longleftrightarrow: '↔',
  leftrightarrow: '↔',
  Rightarrow: '⇒',
  Leftarrow: '⇐',
  Leftrightarrow: '⇔',
  gets: '←',
  to: '→',
  uparrow: '↑',
  downarrow: '↓',
  Uparrow: '⇑',
  Downarrow: '⇓',
  times: '×',
  cdot: '·',
  pm: '±',
  mp: '∓',
  leq: '≤',
  geq: '≥',
  neq: '≠',
  approx: '≈',
  le: '≤',
  ge: '≥',
  ne: '≠',
  infty: '∞',
  ldots: '…',
  cdots: '⋯',
  alpha: 'α',
  beta: 'β',
  gamma: 'γ',
  delta: 'δ',
  epsilon: 'ε',
  theta: 'θ',
  lambda: 'λ',
  mu: 'μ',
  pi: 'π',
  sigma: 'σ',
  phi: 'φ',
  omega: 'ω',
  Delta: 'Δ',
  Sigma: 'Σ',
  Omega: 'Ω',
  Pi: 'Π',
};

const SUP: Record<string, string> = {
  '0': '⁰',
  '1': '¹',
  '2': '²',
  '3': '³',
  '4': '⁴',
  '5': '⁵',
  '6': '⁶',
  '7': '⁷',
  '8': '⁸',
  '9': '⁹',
  '+': '⁺',
  '-': '⁻',
  '=': '⁼',
  '(': '⁽',
  ')': '⁾',
  n: 'ⁿ',
  i: 'ⁱ',
};

const SUB: Record<string, string> = {
  '0': '₀',
  '1': '₁',
  '2': '₂',
  '3': '₃',
  '4': '₄',
  '5': '₅',
  '6': '₆',
  '7': '₇',
  '8': '₈',
  '9': '₉',
  '+': '₊',
  '-': '₋',
  '=': '₌',
  '(': '₍',
  ')': '₎',
  a: 'ₐ',
  e: 'ₑ',
  h: 'ₕ',
  i: 'ᵢ',
  j: 'ⱼ',
  k: 'ₖ',
  l: 'ₗ',
  m: 'ₘ',
  n: 'ₙ',
  o: 'ₒ',
  p: 'ₚ',
  r: 'ᵣ',
  s: 'ₛ',
  t: 'ₜ',
  u: 'ᵤ',
  v: 'ᵥ',
  x: 'ₓ',
};

const COMMAND_PATTERN = new RegExp(
  `\\\\(${Object.keys(COMMANDS)
    .sort((a, b) => b.length - a.length)
    .join('|')})\\b`,
  'g',
);

function outsideCode(source: string, map: (text: string) => string): string {
  return source
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) => (index % 2 === 1 ? part : map(part)))
    .join('');
}

function scripted(body: string, glyphs: Record<string, string>, mark: string): string {
  const chars = [...body];
  if (chars.length > 0 && chars.every((ch) => glyphs[ch])) {
    return chars.map((ch) => glyphs[ch]).join('');
  }
  return `${mark}(${body})`;
}

function simplifyTex(tex: string): string {
  let text = tex.trim();
  text = text.replace(/\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g, '$1');
  text = text.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)');
  text = text.replace(/\\sqrt\{([^{}]*)\}/g, '√($1)');
  text = text.replace(/\\(?:left|right)\b/g, '');
  text = text.replace(COMMAND_PATTERN, (_, name: string) => COMMANDS[name] ?? name);
  text = text.replace(/\^\{([^{}]+)\}/g, (_, body: string) => scripted(body, SUP, '^'));
  text = text.replace(/\^([0-9n+\-=()i])/g, (_, ch: string) => SUP[ch] ?? ch);
  text = text.replace(/_\{([^{}]+)\}/g, (_, body: string) => scripted(body, SUB, '_'));
  text = text.replace(/_([0-9aehijklmnoprstuvx])/g, (_, ch: string) => SUB[ch] ?? ch);
  text = text.replace(/[{}]/g, '');
  return text.replace(/[ \t]{2,}/g, ' ').trim();
}

function unwrapMath(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex: string) => simplifyTex(tex))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex: string) => simplifyTex(tex))
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex: string) => simplifyTex(tex))
    .replace(/(?<!\$)\$(?!\$)((?:\\.|[^$\n])+?)\$/g, (_, tex: string) => simplifyTex(tex));
}

/** コピーと書き出し用。コードの中は変えず、数式だけ読める文字にする。 */
export function latexToPlain(source: string): string {
  return outsideCode(source, unwrapMath);
}

/** `\[...\]` と `\(...\)` を、画面の数式処理が読める `$` 記法に揃える。 */
export function normalizeMathDelimiters(source: string): string {
  return outsideCode(source, (text) =>
    text
      .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex: string) => `$$${tex}$$`)
      .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex: string) => `$${tex}$`),
  );
}

/** 組版済みの回答から、数式を読める文字に戻して本文を取る。 */
export function plainFromRendered(root: HTMLElement): string {
  const clone = root.cloneNode(true) as HTMLElement;
  const nodes = [...clone.querySelectorAll('.katex-display, .katex')].filter(
    (el) => !el.parentElement?.closest('.katex-display, .katex'),
  );
  for (const el of nodes) {
    const tex = el.querySelector('annotation[encoding="application/x-tex"]')?.textContent?.trim();
    el.replaceWith(tex ? latexToPlain(`$${tex}$`) : '');
  }
  return clone.innerText.trim();
}
