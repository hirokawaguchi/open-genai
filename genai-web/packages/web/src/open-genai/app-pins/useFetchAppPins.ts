import useSWR from 'swr';
import { teamApiFetcher } from '@/lib/fetcher';
import type { AppPin, AppPinsResponse } from './types';

const fetchAppPins = async (): Promise<AppPin[]> => {
  try {
    const res = await teamApiFetcher<AppPinsResponse>('my/app-pins');
    return res.pins ?? [];
  } catch {
    return [];
  }
};

export const useFetchAppPins = () => {
  const { data, mutate } = useSWR<AppPin[]>('my/app-pins', fetchAppPins, {
    suspense: false,
    revalidateOnFocus: false,
  });

  return { pins: data ?? [], mutate };
};
