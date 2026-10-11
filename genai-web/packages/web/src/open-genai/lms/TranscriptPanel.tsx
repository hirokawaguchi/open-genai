import { useEffect, useRef, useState } from 'react';
import { PiSpinnerGap } from 'react-icons/pi';
import { teamApi } from '@/lib/fetcher';
import { Button } from '@/components/ui/dads/Button';
import { transcriptStatusLabel } from './labels';
import type { MaterialTranscript, TranscriptSegment } from './types';
import { errorMessage, useLmsTranscript } from './useLms';

type Props = {
  materialId: string;
  onChanged: () => void;
};

const clock = (value: number) => {
  const total = Math.max(0, Math.floor(value));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
};

const sameSegments = (left: TranscriptSegment[], right: TranscriptSegment[]) =>
  JSON.stringify(left) === JSON.stringify(right);

export const TranscriptPanel = ({ materialId, onChanged }: Props) => {
  const { transcript, isLoading, error, mutate } = useLmsTranscript(materialId);
  const [rows, setRows] = useState<TranscriptSegment[]>([]);
  const [note, setNote] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const stopAt = useRef<number | null>(null);
  const rowsRef = useRef(rows);
  const dirtyRef = useRef(false);
  const seenRef = useRef('');
  const [playing, setPlaying] = useState<string | null>(null);
  const [pdfPage, setPdfPage] = useState(1);
  rowsRef.current = rows;

  useEffect(() => {
    if (!transcript || transcript.materialId !== materialId) {
      return;
    }
    if (transcript.status === 'running') {
      seenRef.current = `${materialId}:running`;
      dirtyRef.current = false;
      setRows([]);
      return;
    }
    const token = `${transcript.materialId}:${transcript.updatedAt}:${transcript.status}`;
    if (seenRef.current === token || dirtyRef.current) {
      return;
    }
    seenRef.current = token;
    if (!sameSegments(transcript.segments, rowsRef.current)) {
      setRows(transcript.segments);
    }
  }, [transcript, materialId]);

  const persist = async (): Promise<boolean> => {
    if (!dirtyRef.current) {
      return true;
    }
    const snapshot = rowsRef.current;
    setNote('本文を保存しています');
    setLocalError(null);
    try {
      const saved = await teamApi
        .put<MaterialTranscript>(`lms/materials/${materialId}/transcript`, { segments: snapshot })
        .then((res) => res.data);
      if (sameSegments(snapshot, rowsRef.current)) {
        dirtyRef.current = false;
        seenRef.current = `${saved.materialId}:${saved.updatedAt}:${saved.status}`;
      }
      await mutate(saved, { revalidate: false });
      setNote(saved.status === 'draft' ? '下書きを保存しました。確定すると本文が残ります。' : '本文を保存しました');
      onChanged();
      return !dirtyRef.current;
    } catch (e) {
      setNote('');
      setLocalError(errorMessage(e, '本文を保存できませんでした'));
      return false;
    }
  };

  useEffect(() => {
    if (!dirtyRef.current) {
      return;
    }
    const timer = window.setTimeout(() => {
      void persist();
    }, 700);
    return () => window.clearTimeout(timer);
  }, [rows, materialId]);

  useEffect(() => {
    const flush = () => {
      if (!dirtyRef.current) {
        return;
      }
      void teamApi.put(`lms/materials/${materialId}/transcript`, { segments: rowsRef.current });
    };
    window.addEventListener('pagehide', flush);
    return () => {
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [materialId]);

  const editRows = (next: TranscriptSegment[]) => {
    dirtyRef.current = true;
    setRows(next);
    setNote('下書きに残します');
  };

  const playSpan = (segment: TranscriptSegment) => {
    const node = videoRef.current;
    if (!node) {
      return;
    }
    setPlaying(segment.id);
    stopAt.current = segment.end;
    const seek = () => {
      node.currentTime = segment.start;
      void node.play();
    };
    if (node.readyState >= 1) {
      seek();
    } else {
      node.addEventListener('loadedmetadata', seek, { once: true });
    }
  };

  const startJob = async (redo: boolean) => {
    if (redo && !window.confirm('いまの本文を消して、文字起こしをやり直しますか。')) {
      return;
    }
    setLocalError(null);
    setNote(redo ? 'やり直しています' : '文字起こしを始めています');
    try {
      const saved = await teamApi
        .post<MaterialTranscript>(`lms/materials/${materialId}/transcript`, { redo })
        .then((res) => res.data);
      seenRef.current = '';
      dirtyRef.current = false;
      setNote('');
      await mutate(saved, { revalidate: false });
      onChanged();
    } catch (e) {
      setNote('');
      setLocalError(errorMessage(e, '文字起こしを始められませんでした'));
    }
  };

  const confirm = async () => {
    setConfirming(true);
    setLocalError(null);
    try {
      const ready = await persist();
      if (!ready) {
        return;
      }
      const saved = await teamApi
        .post<MaterialTranscript>(`lms/materials/${materialId}/transcript/confirm`)
        .then((res) => res.data);
      seenRef.current = `${saved.materialId}:${saved.updatedAt}:${saved.status}`;
      await mutate(saved, { revalidate: false });
      onChanged();
      setNote('本文を確定しました');
    } catch (e) {
      setLocalError(errorMessage(e, '本文を確定できませんでした'));
    } finally {
      setConfirming(false);
    }
  };

  if (isLoading && !transcript) {
    return <p className='text-solid-gray-600'>読み込み中…</p>;
  }
  if (!transcript) {
    return <p className='text-red-700'>{errorMessage(error, '本文を表示できませんでした')}</p>;
  }

  const slides = transcript.kind === 'slides';
  const running = transcript.status === 'running';
  const hasText = rows.some((row) => row.text.trim());
  const statusText = transcriptStatusLabel(transcript.status);

  return (
    <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-hidden'>
      <div className='flex shrink-0 flex-col gap-2'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='min-w-0'>
            <h2 className='truncate text-std-16B-170 text-solid-gray-900'>{transcript.title}</h2>
            <p className='text-dns-14N-130 text-solid-gray-600'>
              {slides
                ? '左が PDF、右がページごとの本文です。文字の少ないページには、画像の説明を足します。'
                : '左が動画、右が発話ごとの本文です。行を選ぶとその区間だけ再生します。'}
              状態: {statusText}
            </p>
          </div>
          <span className='inline-flex gap-2'>
            {transcript.status === 'none' || transcript.status === 'failed' ? (
              <Button type='button' variant='outline' size='sm' onClick={() => void startJob(false)}>
                文字起こしを作る
              </Button>
            ) : (
              <Button type='button' variant='outline' size='sm' onClick={() => void startJob(true)}>
                やり直す
              </Button>
            )}
            <Button type='button' variant='solid-fill' size='sm' onClick={() => void confirm()} disabled={running || confirming || !hasText}>
              確定する
            </Button>
          </span>
        </div>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          編集内容は下書きに自動で残ります。本文を直すと、確定は外れます。
        </p>
        {(running || note || transcript.notice || transcript.error || localError) && (
          <p
            className={`flex items-center gap-2 ${localError || transcript.error ? 'text-dns-14N-130 text-red-700' : 'text-dns-14N-130 text-solid-gray-700'}`}
            role='status'
          >
            {running && <PiSpinnerGap aria-hidden={true} className='size-5 shrink-0 animate-spin text-blue-900' />}
            {localError || transcript.error || note || transcript.notice || '文字起こしを実行しています'}
          </p>
        )}
      </div>
      <div className='grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(14rem,42%)_minmax(0,1fr)] gap-3 overflow-hidden lg:grid-cols-2 lg:grid-rows-1'>
        <div className='min-h-0 overflow-hidden rounded-8 bg-black'>
          {transcript.playbackUrl && !slides && (
            <video
              ref={videoRef}
              className='h-full w-full object-contain'
              src={transcript.playbackUrl}
              controls
              onTimeUpdate={() => {
                const node = videoRef.current;
                if (!node || stopAt.current == null) {
                  return;
                }
                if (node.currentTime >= stopAt.current) {
                  node.pause();
                  stopAt.current = null;
                }
              }}
            />
          )}
          {transcript.playbackUrl && slides && (
            <iframe
              title={`${transcript.title} の PDF`}
              className='h-full w-full bg-white'
              src={`${transcript.playbackUrl}#page=${pdfPage}`}
            />
          )}
          {!transcript.playbackUrl && (
            <p className='p-4 text-dns-14N-130 text-white'>プレビューを表示できません</p>
          )}
        </div>
        <div className='flex h-full min-h-0 flex-col gap-3 overflow-y-auto overscroll-contain'>
      {running && (
        <p className='flex items-center gap-2 text-solid-gray-600' role='status'>
          <PiSpinnerGap aria-hidden={true} className='size-5 shrink-0 animate-spin text-blue-900' />
          文字起こしを実行しています。完了まで数分かかることがあります。
        </p>
      )}
      {!running && transcript.status !== 'none' && transcript.status !== 'failed' && rows.length === 0 && !transcript.notice && (
        <p className='text-solid-gray-700'>本文がありません</p>
      )}
      {!running &&
        rows.map((row, index) => (
          <div
            key={row.id}
            className={`flex h-full min-h-full shrink-0 flex-col rounded-8 border p-3 ${playing === row.id ? 'border-blue-900 bg-blue-50' : 'border-solid-gray-420'}`}
          >
            <div className='mb-2 flex shrink-0 flex-wrap items-center justify-between gap-2'>
              {slides ? (
                <button
                  type='button'
                  className={`text-std-16B-150 ${pdfPage === row.start ? 'text-blue-900' : 'text-solid-gray-900'}`}
                  onClick={() => setPdfPage(row.start)}
                >
                  ページ {row.start}
                </button>
              ) : (
                <button type='button' className='text-std-16B-150 text-blue-900' onClick={() => playSpan(row)}>
                  {clock(row.start)}–{clock(row.end)} を再生
                </button>
              )}
              {!slides && (
                <span className='inline-flex gap-2'>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={row.text.trim().length < 2}
                    onClick={() => {
                      const cut = Math.max(1, Math.floor(row.text.length / 2));
                      const mid = Math.round((row.start + (row.end - row.start) / 2) * 100) / 100;
                      const right: TranscriptSegment = {
                        id: crypto.randomUUID(),
                        start: mid,
                        end: row.end,
                        text: row.text.slice(cut).trimStart(),
                      };
                      const left: TranscriptSegment = { ...row, end: mid, text: row.text.slice(0, cut).trimEnd() };
                      editRows([...rows.slice(0, index), left, right, ...rows.slice(index + 1)]);
                    }}
                  >
                    分割
                  </Button>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    disabled={index === 0}
                    onClick={() => {
                      const prev = rows[index - 1];
                      const merged: TranscriptSegment = {
                        ...prev,
                        end: row.end,
                        text: `${prev.text}${prev.text && row.text ? '\n' : ''}${row.text}`,
                      };
                      editRows([...rows.slice(0, index - 1), merged, ...rows.slice(index + 1)]);
                    }}
                  >
                    前と結合
                  </Button>
                </span>
              )}
            </div>
            <textarea
              className='min-h-0 w-full flex-1 resize-none rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
              value={row.text}
              aria-label={slides ? `ページ ${row.start} の本文` : `${clock(row.start)} からの本文`}
              placeholder={slides ? 'このページから文字を読み取れませんでした' : 'この区間の本文'}
              onChange={(event) => {
                const text = event.target.value;
                editRows(rows.map((item) => (item.id === row.id ? { ...item, text } : item)));
              }}
            />
          </div>
        ))}
        </div>
      </div>
    </div>
  );
};
