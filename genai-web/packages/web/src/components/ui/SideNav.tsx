import { Link, useLocation } from 'react-router';
import { useExApps } from '@/features/exapps/hooks/useExApps';
import { useFilteredTeams } from '@/features/exapps/hooks/useFilteredTeams';
import {
  ALL_APPS_NAV_ITEM,
  pinnedAppHref,
  useRecommendedNavItems,
} from '@/layout/navItems';
import { partitionPinnedApps } from '@/open-genai/app-pins/partitionPinnedApps';
import { useFetchAppPins } from '@/open-genai/app-pins/useFetchAppPins';

const navLinkClass = (active: boolean) =>
  [
    'block rounded-8 px-3 py-2 text-oln-16N-100 text-solid-gray-800',
    'hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)]',
    'focus-visible:bg-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-2 focus-visible:outline-black',
    active ? 'bg-blue-50 text-blue-900 font-bold hover:no-underline' : '',
  ].join(' ');

const isActivePath = (pathname: string, to: string): boolean => {
  if (to === '/') {
    return pathname === '/';
  }
  return pathname === to || pathname.startsWith(`${to}/`);
};

type Props = {
  className?: string;
};

export const SideNav = (props: Props) => {
  const { className } = props;
  const { pathname } = useLocation();
  const recommended = useRecommendedNavItems();
  const { exAppOptions } = useExApps();
  const { filteredTeams } = useFilteredTeams(exAppOptions, []);
  const { pins } = useFetchAppPins();
  const { pinnedItems } = partitionPinnedApps(filteredTeams, pins);

  return (
    <nav
      aria-label='サイドナビゲーション'
      className={`hidden md:flex w-60 shrink-0 flex-col gap-6 border-r border-solid-gray-420 bg-white px-3 py-6 ${className ?? ''}`}
    >
      <div>
        <h2 className='mb-2 px-3 text-dns-14B-130 text-solid-gray-600'>おすすめ</h2>
        <ul className='flex flex-col gap-0.5'>
          {recommended.map((item) => {
            const active = isActivePath(pathname, item.to);
            return (
              <li key={item.to}>
                <Link
                  to={item.to}
                  state={item.state}
                  aria-current={active ? 'page' : undefined}
                  className={navLinkClass(active)}
                  title={item.description}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      {pinnedItems.length > 0 && (
        <div>
          <h2 className='mb-2 px-3 text-dns-14B-130 text-solid-gray-600'>ピン留め</h2>
          <ul className='flex flex-col gap-0.5'>
            {pinnedItems.map((item) => {
              const href = pinnedAppHref(item);
              const active = isActivePath(pathname, href);
              return (
                <li key={`pin-${item.teamIdKey}-${item.app.value}`}>
                  <Link
                    to={href}
                    aria-current={active ? 'page' : undefined}
                    className={navLinkClass(active)}
                    title={item.app.description || item.teamName}
                  >
                    <span className='block truncate'>{item.app.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div>
        <ul className='flex flex-col gap-0.5'>
          <li>
            <Link
              to={ALL_APPS_NAV_ITEM.to}
              aria-current={isActivePath(pathname, ALL_APPS_NAV_ITEM.to) ? 'page' : undefined}
              className={navLinkClass(isActivePath(pathname, ALL_APPS_NAV_ITEM.to))}
            >
              {ALL_APPS_NAV_ITEM.label}
            </Link>
          </li>
        </ul>
      </div>
    </nav>
  );
};
