import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { SearchIcon } from '@/components/ui/icons/SearchIcon';
import { useAccessibilityAnnouncer } from '@/hooks/useAccessibilityAnnouncer';
import { toPinKey } from '@/open-genai/app-pins/appPinKey';
import { MAX_APP_PINS } from '@/open-genai/app-pins/types';
import { useFetchAppPins } from '@/open-genai/app-pins/useFetchAppPins';
import { useToggleAppPin } from '@/open-genai/app-pins/useToggleAppPin';
import { useFilteredTeams } from '../hooks/useFilteredTeams';
import { ExAppOptions } from '../types';
import { ExAppListCard } from './ExAppListCard';

type Props = {
  exAppOptions: ExAppOptions;
  setTeamId: (teamId: string) => void;
  setExAppId: (exAppId: string) => void;
};

export const ExAppList = (props: Props) => {
  const { exAppOptions, setTeamId, setExAppId } = props;

  const [searchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') ?? '');
  const { announceMessage, announce, clearAnnounce } = useAccessibilityAnnouncer();

  const searchWords = useMemo(() => {
    return searchQuery
      .split(' ')
      .flatMap((q) => q.split('　'))
      .filter((q) => q !== '');
  }, [searchQuery]);

  const { filteredTeams } = useFilteredTeams(exAppOptions, searchWords);
  const { pins } = useFetchAppPins();
  const { pin, unpin, error: pinError } = useToggleAppPin();

  const pinnedKeys = useMemo(
    () => new Set(pins.map((p) => toPinKey(p.teamId, p.itemId))),
    [pins],
  );
  const pinLimitReached = pins.length >= MAX_APP_PINS;

  const totalAppsCount = filteredTeams.reduce((sum, team) => sum + team.filteredExApps.length, 0);

  useEffect(() => {
    if (searchWords.length === 0) {
      clearAnnounce();
      return;
    }

    const searchTerm = searchWords.join(' ');

    if (totalAppsCount === 0) {
      announce(`「${searchTerm}」に該当するAIアプリはありません`);
    } else {
      announce(`「${searchTerm}」で${totalAppsCount}件のAIアプリが絞り込まれました`);
    }
  }, [totalAppsCount, searchWords, announce, clearAnnounce]);

  return (
    <>
      <search className='relative mb-2 flex w-full flex-col gap-1.5'>
        <Label htmlFor='filter-apps-input' size='md'>
          名前・説明でAIアプリを絞り込む
        </Label>
        <div className='relative'>
          <Input
            className='w-full pl-10'
            id='filter-apps-input'
            type='text'
            blockSize='md'
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value ?? '');
            }}
          />
          <SearchIcon
            aria-hidden={true}
            className='pointer-events-none absolute top-3.5 left-3 size-5'
          />
        </div>
      </search>

      {pinError && (
        <p className='mt-2 text-dns-14N-130 text-error-1' role='alert'>
          {pinError}
        </p>
      )}

      {filteredTeams.length === 0 ? (
        <p className='mt-8 text-std-16N-170'>該当するAIアプリはありません。</p>
      ) : (
        filteredTeams.map(({ teamIdKey, teamData, filteredExApps }) => (
          <section key={teamIdKey}>
            <h2 className='mt-8 mb-4 flex justify-start text-std-18B-160'>
              {teamData.teamName}（{filteredExApps.length}）
            </h2>
            <ul className='grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4'>
              {filteredExApps.map((exApp) => {
                const isPinned = pinnedKeys.has(toPinKey(teamIdKey, exApp.value));
                return (
                  <li key={`${teamIdKey}-${exApp.value}`}>
                    <ExAppListCard
                      href={exApp.isDefault ? `/${exApp.value}` : `/apps/${teamIdKey}/${exApp.value}`}
                      label={exApp.label}
                      description={exApp.description}
                      onClick={() => {
                        if (!exApp.isDefault) {
                          setTeamId(teamIdKey);
                          setExAppId(exApp.value);
                        }
                      }}
                      highlightWords={searchWords}
                      pinControl={{
                        isPinned,
                        disabled: pinLimitReached,
                        onToggle: () =>
                          isPinned ? unpin(teamIdKey, exApp.value) : pin(teamIdKey, exApp.value),
                      }}
                    />
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
      <div role='status' className='sr-only'>
        {announceMessage}
      </div>
    </>
  );
};
