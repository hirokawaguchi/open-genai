import { useRef } from 'react';
import { ModelSelector } from '@/features/generate-image/components/ModelSelector';
import { useStickyHeader } from '@/features/generate-image/hooks/useStickyHeader';

type Props = {
  title?: string;
};

export const GenerateImageStickyHeader = (props: Props) => {
  const title = props.title || '画像を生成';
  const sentinelRef = useRef<HTMLDivElement>(null);
  const isSticky = useStickyHeader(sentinelRef);

  return (
    <>
      <div ref={sentinelRef} aria-hidden='true' className='h-px' />
      <div
        className={`
          pt-2.5 z-1 group/sticky data-[is-sticky='true']:sticky data-[is-sticky='true']:top-(--header-height) data-[is-sticky='true']:bg-white
        `}
        data-is-sticky={isSticky}
      >
        <div className='flex items-center gap-4 border-b border-b-solid-gray-800 pb-2.5 lg:gap-6'>
          <p
            aria-hidden={true}
            className='hidden text-std-16B-170 group-data-[is-sticky="true"]/sticky:block'
          >
            {title}
          </p>
          <ModelSelector />
        </div>
      </div>
    </>
  );
};
