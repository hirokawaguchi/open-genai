import { Link } from 'react-router';
import type { IconType } from 'react-icons';

export type PatchformPaneTab = {
  id: string;
  label: string;
  to: string;
  icon: IconType;
};

export const PatchformPaneTabs = ({
  current,
  tabs,
  label,
}: {
  current: string;
  tabs: readonly PatchformPaneTab[];
  label: string;
}) => (
  <div className='flex flex-wrap gap-2 border-b border-solid-gray-300' role='tablist' aria-label={label}>
    {tabs.map((t) => {
      const Icon = t.icon;
      return (
        <Link
          key={t.id}
          to={t.to}
          role='tab'
          aria-selected={current === t.id}
          className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-4 py-2 text-oln-16B-100 ${
            current === t.id
              ? 'border-blue-900 text-blue-900'
              : 'border-transparent text-solid-gray-600 hover:text-solid-gray-900'
          }`}
        >
          <Icon aria-hidden={true} className='size-5' />
          {t.label}
        </Link>
      );
    })}
  </div>
);
