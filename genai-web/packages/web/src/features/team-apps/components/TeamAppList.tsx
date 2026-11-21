import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react';
import { ExApp } from 'genai-web';
import { useState } from 'react';
import { PiClipboard, PiDownloadSimple, PiPencilLine, PiTrash } from 'react-icons/pi';
import { Link } from 'react-router';
import {
  linkActiveStyle,
  linkDefaultStyle,
  linkFocusStyle,
  linkHoverStyle,
} from '@/components/ui/dads/Link';
import { MoreVertIcon } from '@/components/ui/icons/MoreVertIcon';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { builtinRouteOf, isBuiltinExApp } from '@/features/exapps/utils/builtinExApp';
import { useFocusNewItemOnLoadMore } from '@/hooks/useFocusNewItemOnLoadMore';
import { download } from '@/utils/createDownloadLink';
import { formatDateTime } from '@/utils/formatDateTime';
import { useFetchLoginUser } from '../hooks/useFetchLoginUser';
import { useFetchTeamAppForJsonDownload } from '../hooks/useFetchTeamAppForJsonDownload';
import { useMoveTeamAppOrder } from '../hooks/useMoveTeamAppOrder';
import { useTeamApps } from '../hooks/useTeamApps';
import { placeTeamApps, swapTeamApp } from '../utils/reorderTeamApps';
import { ExAppStatusChipLabel } from './ExAppStatusChipLabel';

type Props = {
  handleOpenDeleteModal: (app: ExApp) => void;
};

export const TeamAppList = (props: Props) => {
  const { handleOpenDeleteModal } = props;

  const { isSystemAdminGroup, loginUser } = useFetchLoginUser();
  const { fetchTeamAppForJsonDownload } = useFetchTeamAppForJsonDownload();

  const { apps, hasMore, isValidating, loadMore, mutate } = useTeamApps();
  const { moveTeamApp, errorMessage } = useMoveTeamAppOrder();
  const [movingId, setMovingId] = useState<string | null>(null);
  const [movedId, setMovedId] = useState<string | null>(null);
  const [moveError, setMoveError] = useState('');
  const [moveMessage, setMoveMessage] = useState('');

  const onMove = async (exAppId: string, direction: 'up' | 'down') => {
    const next = swapTeamApp(apps, exAppId, direction);
    if (!next) {
      return;
    }
    const name = apps.find((app) => app.exAppId === exAppId)?.exAppName ?? '';
    setMovingId(exAppId);
    setMovedId(exAppId);
    setMoveError('');
    setMoveMessage('');
    try {
      await mutate(
        async (pages) => {
          await moveTeamApp(exAppId, direction);
          return placeTeamApps(pages, next);
        },
        {
          optimisticData: (pages) => placeTeamApps(pages, next),
          rollbackOnError: true,
          revalidate: true,
        },
      );
      setMoveMessage(`「${name}」を一つ${direction === 'up' ? '上' : '下'}へ動かしました`);
    } catch (e) {
      setMovedId(null);
      setMoveError(errorMessage(e));
    } finally {
      setMovingId(null);
    }
  };

  const { listRef, loadMoreWithFocus } = useFocusNewItemOnLoadMore<HTMLUListElement>({
    itemsLength: apps.length,
    focusSelector: 'a',
  });

  if (!isValidating && (!apps || apps.length === 0)) {
    return <p className='mt-6'>AIアプリが登録されていません</p>;
  }

  return (
    <>
      <h2
        tabIndex={-1}
        id='exapp-list-heading'
        className={`my-4 inline-flex text-std-18B-160 focus-visible:rounded-4 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid lg:text-std-20B-150`}
      >
        AIアプリ
      </h2>
      <p className='mb-2 text-std-16N-170'>
        上へ・下へを押すと、この一覧の位置がすぐ入れ替わります。AIアプリページも同じ順になります。
      </p>
      {moveMessage && (
        <p className='mb-2 text-std-16N-170' role='status'>
          {moveMessage}
        </p>
      )}
      {moveError && (
        <p className='mb-2 text-dns-14N-130 text-error-1' role='alert'>
          {moveError}
        </p>
      )}
      <ul ref={listRef} className='flex w-full flex-col'>
        {apps.map((app, index) => {
          const lastUpdated = app.updatedDate || app.createdDate;
          const builtin = isBuiltinExApp(app);
          const href = builtinRouteOf(app.config) || `/apps/${app.teamId}/${app.exAppId}`;
          return (
            <li
              id={`team-app-row-${app.exAppId}`}
              className={`relative grid w-full grid-cols-[1fr_auto] items-center border-b border-solid border-solid-gray-420 ${app.exAppId === movedId ? 'bg-yellow-100' : ''}`}
              key={app.exAppId}
            >
              <div className='flex flex-col items-start gap-4 px-4 py-4 text-dns-16N-130 leading-tight!'>
                <Link
                  to={href}
                  className={`${linkDefaultStyle} ${linkHoverStyle} ${linkFocusStyle} ${linkActiveStyle}`}
                >
                  {app.exAppName}
                </Link>
                <ul className='flex items-baseline gap-2'>
                  {app.status && (
                    <li>
                      <ExAppStatusChipLabel status={app.status} />
                    </li>
                  )}
                  <li>
                    <time
                      className='text-dns-14N-130'
                      dateTime={new Date(Number(lastUpdated)).toISOString()}
                    >
                      最終更新日時：
                      <span>{formatDateTime(lastUpdated)}</span>
                    </time>
                  </li>
                </ul>
              </div>

              <div className='relative flex flex-none items-center px-2'>
                <button
                  type='button'
                  aria-label={`${app.exAppName}を一つ上へ`}
                  disabled={index === 0 || movingId !== null}
                  onClick={() => {
                    void onMove(app.exAppId, 'up');
                  }}
                  className='rounded-4 px-2 py-2 text-oln-16N-100 text-solid-gray-800 hover:bg-solid-gray-50 focus-visible:bg-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-black disabled:text-solid-gray-420'
                >
                  上へ
                </button>
                <button
                  type='button'
                  aria-label={`${app.exAppName}を一つ下へ`}
                  disabled={index === apps.length - 1 || movingId !== null}
                  onClick={() => {
                    void onMove(app.exAppId, 'down');
                  }}
                  className='rounded-4 px-2 py-2 text-oln-16N-100 text-solid-gray-800 hover:bg-solid-gray-50 focus-visible:bg-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-black disabled:text-solid-gray-420'
                >
                  下へ
                </button>
                <Menu>
                  <Tooltip placement='left'>
                    <TooltipTrigger asChild>
                      <MenuButton
                        className={`flex size-9 items-center justify-center rounded-4 after:absolute after:-inset-full after:m-auto after:h-11 after:w-11 hover:bg-solid-gray-50 hover:-outline-offset-[calc(2/16*1rem)] hover:outline-black hover:outline-solid focus-visible:bg-yellow-300 focus-visible:ring-[calc(6/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid focus-visible:ring-inset`}
                      >
                        <MoreVertIcon aria-label='AIアプリの操作' role='img' className='mt-0.5' />
                      </MenuButton>
                    </TooltipTrigger>
                    <TooltipContent aria-hidden={true}>AIアプリの操作</TooltipContent>
                  </Tooltip>

                  <MenuItems
                    modal={false}
                    className={`absolute top-full right-0 z-10 w-auto min-w-fit rounded-8 border border-solid-gray-420 bg-white py-2 shadow-1 focus:outline-hidden`}
                  >
                    <MenuItem>
                      {({ focus }) => (
                        <Link
                          to={`/teams/${app.teamId}/apps/${app.exAppId}/edit`}
                          className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                        >
                          <PiPencilLine aria-hidden={true} className='text-lg' />
                          編集
                        </Link>
                      )}
                    </MenuItem>
                    {app.copyable && (isSystemAdminGroup || loginUser?.isAdmin) && (
                      <MenuItem>
                        {({ focus }) => (
                          <Link
                            to={`/teams/${app.teamId}/apps/${app.exAppId}/copy`}
                            className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-solid-gray-800 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                          >
                            <PiClipboard aria-hidden={true} className='text-lg' />
                            AIアプリをコピー
                          </Link>
                        )}
                      </MenuItem>
                    )}
                    <MenuItem>
                      {({ focus }) => (
                        <button
                          type='button'
                          onClick={async () => {
                            const res = await fetchTeamAppForJsonDownload(app.teamId, app.exAppId);
                            const blob = new Blob([JSON.stringify(res, null, 2)], {
                              type: 'application/json',
                            });
                            const url = URL.createObjectURL(blob);
                            download(url, `${app.exAppId}.json`);
                          }}
                          aria-haspopup='dialog'
                          className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                        >
                          <PiDownloadSimple aria-hidden={true} className='text-lg' />
                          JSONダウンロード
                        </button>
                      )}
                    </MenuItem>
                    {!builtin && (
                      <MenuItem>
                        {({ focus }) => (
                          <button
                            type='button'
                            onClick={() => handleOpenDeleteModal(app)}
                            className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-error-1 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                          >
                            <PiTrash aria-hidden={true} className='text-lg' />
                            削除
                          </button>
                        )}
                      </MenuItem>
                    )}
                  </MenuItems>
                </Menu>
              </div>
            </li>
          );
        })}
      </ul>

      {hasMore && (
        <LoadingButton
          loading={isValidating}
          onClick={() => loadMoreWithFocus(loadMore)}
          className='mt-6'
          variant='outline'
          size='md'
          type='button'
        >
          {isValidating ? '読み込み中' : 'さらにAIアプリを読み込む'}
        </LoadingButton>
      )}
    </>
  );
};
