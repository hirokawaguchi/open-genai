import { useEffect, useRef } from 'react';
import { useDownloadArtifactCarrier } from '@/features/exapp/hooks/useDownloadArtifactCarrier';
import { ApiError, teamApi } from '@/lib/fetcher';
import { deliverBrowserFile } from './deliverBrowserFile';

type ListedDownload = {
  id: string;
  name: string;
  size?: number;
};

/**
 * 遠隔 Chromium が受け取ったファイルを取り、オフィスと同じ配信で手元へ渡す。
 */
export const useBrowserDownloads = (
  sessionId: string | null,
  delivery: string | undefined,
  onNotice: (text: string) => void,
) => {
  const { downloadCarrier } = useDownloadArtifactCarrier();
  const onNoticeRef = useRef(onNotice);
  onNoticeRef.current = onNotice;
  const deliveryRef = useRef(delivery);
  deliveryRef.current = delivery;
  const carrierRef = useRef(downloadCarrier);
  carrierRef.current = downloadCarrier;

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    let running = false;
    const claimed = new Set<string>();

    const tick = async () => {
      if (cancelled || running) {
        return;
      }
      running = true;
      try {
        const res = await teamApi.get<{ files?: ListedDownload[]; notes?: string[] }>(
          `browser/sessions/${encodeURIComponent(sessionId)}/downloads`,
        );
        if (cancelled) {
          return;
        }
        for (const note of res.data.notes ?? []) {
          if (note) {
            onNoticeRef.current(note);
          }
        }
        for (const file of res.data.files ?? []) {
          if (!file.id || claimed.has(file.id)) {
            continue;
          }
          claimed.add(file.id);
          let got: Awaited<ReturnType<typeof teamApi.getBlob>>;
          try {
            got = await teamApi.getBlob(
              `browser/sessions/${encodeURIComponent(sessionId)}/downloads/${encodeURIComponent(file.id)}`,
            );
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 404) {
              claimed.delete(file.id);
            }
            continue;
          }
          if (cancelled) {
            return;
          }
          const bytes = await got.blob.arrayBuffer();
          const notice = await deliverBrowserFile(
            file.name || 'download',
            bytes,
            deliveryRef.current,
            carrierRef.current,
          );
          if (notice) {
            onNoticeRef.current(notice);
          }
        }
      } catch {
        // セッションが終わっていれば次の周期で止まる。
      } finally {
        running = false;
      }
    };

    void tick();
    const timer = window.setInterval(() => {
      void tick();
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);
};
