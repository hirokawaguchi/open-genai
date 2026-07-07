import { useExApps } from '@/features/exapps/hooks/useExApps';
import { useFilteredTeams } from '@/features/exapps/hooks/useFilteredTeams';
import { ExAppListCard } from '@/features/exapps/components/ExAppListCard';
import { partitionPinnedApps } from './partitionPinnedApps';
import { useFetchAppPins } from './useFetchAppPins';
import { useToggleAppPin } from './useToggleAppPin';

/**
 * トップページ用: 利用者本人がピン留めした AI アプリを表示するセクション。
 * ピンが 0 件のときは何も描画しない。
 */
export const PinnedAppsSection = () => {
  const { exAppOptions, setTeamId, setExAppId } = useExApps();
  const { filteredTeams } = useFilteredTeams(exAppOptions, []);
  const { pins } = useFetchAppPins();
  const { unpin, error: pinError } = useToggleAppPin();

  const { pinnedItems } = partitionPinnedApps(filteredTeams, pins);

  if (pinnedItems.length === 0) {
    return null;
  }

  return (
    <div className='mt-8 lg:mt-10'>
      <h2 className='mb-6 flex justify-start text-std-24B-150'>ピン留め</h2>
      {pinError && (
        <p className='mb-2 text-dns-14N-130 text-error-1' role='alert'>
          {pinError}
        </p>
      )}
      <ul className='grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-4'>
        {pinnedItems.map(({ teamIdKey, teamName, app }) => (
          <li key={`pinned-${teamIdKey}-${app.value}`}>
            <ExAppListCard
              href={app.isDefault ? `/${app.value}` : `/apps/${teamIdKey}/${app.value}`}
              label={app.label}
              description={app.description}
              categoryName={teamName}
              onClick={() => {
                if (!app.isDefault) {
                  setTeamId(teamIdKey);
                  setExAppId(app.value);
                }
              }}
              pinControl={{
                isPinned: true,
                onToggle: () => unpin(teamIdKey, app.value),
              }}
            />
          </li>
        ))}
      </ul>
    </div>
  );
};
