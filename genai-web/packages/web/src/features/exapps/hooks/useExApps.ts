import { useEffect } from 'react';
import { useParams } from 'react-router';
import { KNOWLEDGE_EXAPP_IDS } from '@/layout/navItems';
import { uniqBy } from '@/utils/uniqBy';
import { useExAppStore } from '../stores/useExAppStore';
import type { ExAppOptions } from '../types';
import { useFetchExApps } from './useFetchExApps';

export const useExApps = () => {
  const {
    teamId,
    exAppId,
    exApps,
    teamOptions,
    exAppOptions,
    setTeamId,
    setExAppId,
    setExApps,
    setTeamOptions,
    setExAppOptions,
  } = useExAppStore();

  const { data: newExApps } = useFetchExApps();
  const params = useParams<{ teamId?: string; exAppId?: string }>();

  useEffect(() => {
    if (newExApps && newExApps.length > 0) {
      setExApps(newExApps);

      // draft と、/knowledge へ集約済みの旧管理系（タグ/登録/管理）は一覧から除外
      const publishedExApps = newExApps.filter(
        (exApp) => exApp.status !== 'draft' && !KNOWLEDGE_EXAPP_IDS.has(exApp.exAppId),
      );

      const newTeamOptions = uniqBy(
        publishedExApps.map((exapp) => ({
          value: exapp.teamId,
          label: exapp.teamName,
        })),
        'value',
      );
      setTeamOptions(newTeamOptions);
      const newExAppOptions: ExAppOptions = {};
      publishedExApps.map((m) => {
        if (!newExAppOptions[m.teamId]) {
          newExAppOptions[m.teamId] = {
            teamName: m.teamName,
            exApps: [],
          };
        }

        // 同一チーム内で重複する exAppId をチェック
        const isDuplicate = newExAppOptions[m.teamId].exApps.some(
          (exApp) => exApp.value === m.exAppId,
        );

        if (!isDuplicate) {
          newExAppOptions[m.teamId].exApps.push({
            value: m.exAppId,
            label: m.exAppName,
            description: m.description,
          });
        }
      });
      setExAppOptions(newExAppOptions);
      if (teamId === '' && exAppId === '' && !params.teamId && !params.exAppId) {
        if (publishedExApps.length > 0) {
          setTeamId(publishedExApps[0].teamId);
          setExAppId(publishedExApps[0].exAppId);
        }
      }
    }
  }, [exApps, newExApps, setExApps, setExAppOptions, setTeamOptions]);

  useEffect(() => {
    if (!newExApps || newExApps.length === 0) {
      return;
    }

    const { teamId, exAppId } = params;

    if (!teamId || !exAppId) {
      return;
    }

    // URLパラメータが有効かチェック
    if (!newExApps.find((exApp) => exApp.teamId === teamId)) {
      return;
    }

    if (!newExApps.find((exApp) => exApp.exAppId === exAppId)) {
      return;
    }

    setTeamId(teamId);
    setExAppId(exAppId);
  }, [newExApps, params.teamId, params.exAppId]);

  return {
    teamId,
    exAppId,
    exApps,
    teamOptions,
    exAppOptions,
    setTeamId,
    setExAppId,
  };
};
