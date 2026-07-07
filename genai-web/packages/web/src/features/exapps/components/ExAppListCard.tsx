import { PiPushPin, PiPushPinFill } from 'react-icons/pi';
import { Link } from 'react-router';
import { useHighlight } from '@/hooks/useHighlight';

type PinControl = {
  isPinned: boolean;
  onToggle: () => void;
  disabled?: boolean;
};

type Props = {
  href: string;
  label: string;
  description: string;
  onClick: () => void;
  highlightWords?: string[];
  categoryName?: string;
  pinControl?: PinControl;
};

export const ExAppListCard = (props: Props) => {
  const { href, onClick, label, description, highlightWords = [], categoryName, pinControl } = props;
  const { highlightText } = useHighlight();

  return (
    <Link
      to={href}
      className={`group relative flex h-full flex-col rounded-8 bg-white border border-solid-gray-420 p-4 text-std-16N-175 hover:bg-blue-50 hover:border-solid-gray-500 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid`}
      onClick={onClick}
    >
      {pinControl && (
        <button
          type='button'
          aria-pressed={pinControl.isPinned}
          aria-label={pinControl.isPinned ? 'ピン留めを解除' : 'ピン留め'}
          disabled={pinControl.disabled && !pinControl.isPinned}
          title={
            pinControl.disabled && !pinControl.isPinned
              ? 'ピン留めは8件までです'
              : pinControl.isPinned
                ? 'ピン留めを解除'
                : 'ピン留め'
          }
          className={`absolute top-2 right-2 flex size-8 items-center justify-center rounded-4 hover:bg-blue-100 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid disabled:cursor-not-allowed disabled:opacity-40 ${pinControl.isPinned ? 'text-blue-1000' : 'text-solid-gray-536'}`}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (pinControl.disabled && !pinControl.isPinned) {
              return;
            }
            pinControl.onToggle();
          }}
        >
          {pinControl.isPinned ? (
            <PiPushPinFill aria-hidden={true} className='size-5' />
          ) : (
            <PiPushPin aria-hidden={true} className='size-5' />
          )}
        </button>
      )}
      <div className='flex h-full w-full flex-col'>
        <h3 className='pr-9 text-std-18B-160 underline underline-offset-[calc(3/16*1rem)] group-hover:decoration-[calc(3/16*1rem)]'>
          {highlightText(label, highlightWords)}
        </h3>
        {categoryName && (
          <p className='mt-1 text-dns-14N-130 text-solid-gray-536'>{categoryName}</p>
        )}
        <p className='mt-2 mb-3 text-std-16N-170 underline-offset-[calc(3/16*1rem)] group-hover:underline'>
          {highlightText(description, highlightWords)}
        </p>
      </div>
    </Link>
  );
};
