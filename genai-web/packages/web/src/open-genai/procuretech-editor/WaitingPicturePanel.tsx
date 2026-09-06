/** 生成・書き出し待ち中に表示するプロジェクト識別画像。 */

const FALLBACK_SVG = encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
    <rect width="512" height="512" fill="#fff"/>
    <g fill="none" stroke="#282832" stroke-width="7" stroke-linecap="round">
      <ellipse cx="260" cy="155" rx="90" ry="85"/>
      <ellipse cx="228" cy="148" rx="17" ry="17"/>
      <ellipse cx="294" cy="148" rx="18" ry="20"/>
      <path d="M230 195a40 28 0 0 0 70 8"/>
      <line x1="260" y1="70" x2="248" y2="28"/>
      <ellipse cx="249" cy="25" rx="13" ry="13"/>
      <rect x="175" y="250" width="170" height="150" rx="18"/>
      <rect x="220" y="290" width="80" height="55"/>
      <line x1="175" y1="280" x2="90" y2="340"/>
      <line x1="345" y1="275" x2="430" y2="330"/>
      <ellipse cx="88" cy="342" rx="20" ry="20"/>
      <ellipse cx="433" cy="333" rx="21" ry="21"/>
      <line x1="220" y1="400" x2="200" y2="480"/>
      <line x1="300" y1="400" x2="330" y2="478"/>
      <ellipse cx="202" cy="484" rx="27" ry="16"/>
      <ellipse cx="338" cy="483" rx="30" ry="17"/>
    </g>
    <circle cx="228" cy="148" r="6" fill="#282832"/>
    <circle cx="294" cy="147" r="6" fill="#282832"/>
  </svg>`,
);

export const WAITING_FALLBACK_SRC = `data:image/svg+xml;charset=utf-8,${FALLBACK_SVG}`;

type Props = {
  src?: string | null;
  label: string;
  progress?: number;
};

export const WaitingPicturePanel = ({ src, label, progress }: Props) => (
  <div className='flex flex-col items-center gap-2 rounded-8 border border-blue-300 bg-blue-50 px-3 py-3'>
    <img
      src={src || WAITING_FALLBACK_SRC}
      alt=''
      className='size-48 rounded-8 border border-solid-gray-200 bg-white object-contain'
    />
    <p className='text-dns-14N-130 text-solid-gray-800'>
      {label}
      {typeof progress === 'number' ? `（${progress}%）` : ''}
    </p>
  </div>
);
