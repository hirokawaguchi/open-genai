import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { CATALOG_CATEGORY_LABEL, CATALOG_CATEGORY_ORDER, catalogTypeHelp } from '../labels';
import type { CatalogItem } from '../types';
import { CatalogTypeIcon } from './CatalogTypeIcon';

type Props = {
  catalog: CatalogItem[];
  onAdd: (type: string) => void;
};

export const CatalogPalette = ({ catalog, onAdd }: Props) => {
  const grouped = CATALOG_CATEGORY_ORDER.map((category) => ({
    category,
    items: catalog.filter((c) => c.category === category),
  })).filter((g) => g.items.length > 0);

  return (
    <div className='flex flex-col gap-4'>
      <div>
        <h2 className='text-std-18B-160'>部品を追加</h2>
        <p className='mt-1 text-dns-14N-130 text-solid-gray-700'>
          分類を開いて選んでください。追加後は左（または上）の一覧で設定します。
        </p>
      </div>
      <div className='flex flex-col gap-2'>
        {grouped.map((g, index) => (
          <Disclosure
            key={g.category}
            className='rounded-8 border border-solid-gray-300 bg-white px-3 py-2'
            open={index === 0}
          >
            <DisclosureSummary className='w-full'>
              <span className='text-dns-16B-130 text-solid-gray-800'>
                {CATALOG_CATEGORY_LABEL[g.category] || g.category}
                <span className='ml-1 font-normal text-solid-gray-600'>（{g.items.length}）</span>
              </span>
            </DisclosureSummary>
            <ul className='mt-2 flex flex-col gap-2'>
              {g.items.map((item) => (
                <li key={item.type}>
                  <Tooltip placement='left' strategy='fixed'>
                    <TooltipTrigger asChild>
                      <button
                        type='button'
                        onClick={() => onAdd(item.type)}
                        className='flex w-full items-start gap-2 rounded-8 border border-solid-gray-420 bg-white px-3 py-2 text-left hover:border-blue-900 hover:bg-blue-50'
                      >
                        <CatalogTypeIcon type={item.type} className='mt-0.5 size-5 text-blue-900' />
                        <span className='min-w-0'>
                          <span className='block text-std-16B-150 text-solid-gray-900'>{item.label}</span>
                          {catalogTypeHelp(item.type, item.description) ? (
                            <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-700'>
                              {item.description || catalogTypeHelp(item.type)}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent role='tooltip' aria-hidden={true}>
                      <span className='block max-w-64 whitespace-normal'>
                        {catalogTypeHelp(item.type, item.description)}
                      </span>
                    </TooltipContent>
                  </Tooltip>
                </li>
              ))}
            </ul>
          </Disclosure>
        ))}
      </div>
    </div>
  );
};
