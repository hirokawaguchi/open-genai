import { useMemo } from 'react';
import { COMMON_EXAPPS_TEAM_ID } from '../constants';
import { ExAppOptions } from '../types';
import { sortByDisplayOrder } from '../utils/displayOrder';
import { useExAppFilter } from './useExAppFilter';
import { useFetchCommonTeam } from './useFetchCommonTeam';
import { useGenUApps } from './useGenUApps';

export const useFilteredTeams = (exAppOptions: ExAppOptions, searchWords: string[]) => {
  const { genUApps } = useGenUApps();
  const { commonTeamExists } = useFetchCommonTeam();
  const { filterBySearchWords } = useExAppFilter(searchWords);

  const filteredTeams = useMemo(() => {
    const teams = Object.entries(exAppOptions)
      .map(([teamIdKey, teamData]) => {
        const filteredExApps = filterBySearchWords(teamData.exApps).map((exApp) => ({
          ...exApp,
          isDefault: false,
        }));

        if (teamIdKey === COMMON_EXAPPS_TEAM_ID) {
          const filteredDefaultApps = filterBySearchWords(genUApps).map((exApp) => ({
            ...exApp,
            isDefault: true,
          }));
          const combinedExApps = sortByDisplayOrder([...filteredExApps, ...filteredDefaultApps]);
          return combinedExApps.length > 0
            ? { teamIdKey, teamData, filteredExApps: combinedExApps }
            : null;
        }

        return filteredExApps.length > 0
          ? { teamIdKey, teamData, filteredExApps: sortByDisplayOrder(filteredExApps) }
          : null;
      })
      .filter((team) => team !== null);

    const existingCommonTeam = teams.find((team) => team.teamIdKey === COMMON_EXAPPS_TEAM_ID);
    const fallbackCommonTeam = (() => {
      if (existingCommonTeam || !commonTeamExists || genUApps.length === 0) {
        return undefined;
      }

      const filteredDefaultApps = filterBySearchWords(genUApps).map((exApp) => ({
        ...exApp,
        isDefault: true,
      }));
      if (filteredDefaultApps.length === 0) {
        return undefined;
      }

      return {
        teamIdKey: COMMON_EXAPPS_TEAM_ID,
        teamData: { teamName: '共通アプリ', exApps: [] as typeof filteredDefaultApps },
        filteredExApps: sortByDisplayOrder(filteredDefaultApps),
      };
    })();
    const commonExAppsTeam = existingCommonTeam ?? fallbackCommonTeam;
    const otherTeams = teams.filter((team) => team.teamIdKey !== COMMON_EXAPPS_TEAM_ID);

    otherTeams.sort((a, b) =>
      (a?.teamData.teamName ?? '').localeCompare(b?.teamData.teamName ?? '', 'ja'),
    );

    return commonExAppsTeam ? [commonExAppsTeam, ...otherTeams] : otherTeams;
  }, [exAppOptions, filterBySearchWords, genUApps, commonTeamExists]);

  return { filteredTeams };
};
