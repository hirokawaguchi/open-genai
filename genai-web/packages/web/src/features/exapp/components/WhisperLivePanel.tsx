import { useEffect, useRef, useState } from 'react';
import { useSWRConfig } from 'swr';
import { unstable_serialize } from 'swr/infinite';
import { Button } from '@/components/ui/dads/Button';
import { Divider } from '@/components/ui/dads/Divider';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { Select } from '@/components/ui/dads/Select';
import { SupportText } from '@/components/ui/dads/SupportText';
import { teamApi } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';
import { getExAppHistoriesKey } from '../hooks/useFetchInvokedExAppHistories';
import { whisperLiveUrl } from '../whisperLiveUrl';
import { pcmBase64FromFloat } from '../whisperPcm';
import { applyLiveMessage, type LiveTurn, liveTranscript } from '../whisperTranscript';

type Props = {
  teamId: string;
  exAppId: string;
  shown?: boolean;
  /** 親が言語を持つとき、このパネルでは選ばせない。 */
  language?: string;
  caseTitle?: string;
  embedded?: boolean;
  onSaved?: (createdDate: string) => void;
};

const SPEECH_RMS = 0.015;
const SILENCE_MS = 700;
const MAX_TURN_MS = 12000;

const rmsOf = (samples: Float32Array): number => {
  if (samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    sum += samples[i] * samples[i];
  }
  return Math.sqrt(sum / samples.length);
};

export const WhisperLivePanel = (props: Props) => {
  const { teamId, exAppId, shown = false, caseTitle = '', embedded = false, onSaved } = props;
  const { mutate } = useSWRConfig();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [ownLanguage, setOwnLanguage] = useState('auto');
  const language = props.language ?? ownLanguage;
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [turns, setTurns] = useState<LiveTurn[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const stopCaptureRef = useRef<(() => void) | null>(null);
  const stoppedRef = useRef(false);
  const speakingRef = useRef(false);
  const silenceMsRef = useRef(0);
  const turnMsRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    teamApi
      .get<{ enabled: boolean }>('whisper/live/config')
      .then((res) => {
        if (!cancelled) {
          setEnabled(res.data.enabled === true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setEnabled(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      stoppedRef.current = true;
      stopCaptureRef.current?.();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      void audioContextRef.current?.close();
      socketRef.current?.close();
    };
  }, []);

  const refreshHistories = () => {
    void mutate(unstable_serialize(getExAppHistoriesKey(teamId, exAppId)));
  };

  const stopCapture = () => {
    stopCaptureRef.current?.();
    stopCaptureRef.current = null;
    speakingRef.current = false;
    silenceMsRef.current = 0;
    turnMsRef.current = 0;
  };

  const finish = () => {
    stopCapture();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setActive(false);
    setStatus('');
  };

  const sendJson = (payload: Record<string, string>) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  };

  const onSamples = (samples: Float32Array, sampleRate: number) => {
    const ms = (samples.length / sampleRate) * 1000;
    const loud = rmsOf(samples) >= SPEECH_RMS;
    if (loud) {
      speakingRef.current = true;
      silenceMsRef.current = 0;
      turnMsRef.current += ms;
    } else if (speakingRef.current) {
      silenceMsRef.current += ms;
      turnMsRef.current += ms;
    }
    sendJson({ type: 'audio', audio: pcmBase64FromFloat(samples, sampleRate) });
    if (
      speakingRef.current &&
      (silenceMsRef.current >= SILENCE_MS || turnMsRef.current >= MAX_TURN_MS)
    ) {
      sendJson({ type: 'commit' });
      speakingRef.current = false;
      silenceMsRef.current = 0;
      turnMsRef.current = 0;
    }
  };

  const startCapture = async (stream: MediaStream, context: AudioContext) => {
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const gain = context.createGain();
    gain.gain.value = 0;
    processor.onaudioprocess = (event) => {
      const channel = event.inputBuffer.getChannelData(0);
      onSamples(new Float32Array(channel), context.sampleRate);
    };
    source.connect(processor);
    processor.connect(gain);
    gain.connect(context.destination);
    stopCaptureRef.current = () => {
      processor.onaudioprocess = null;
      source.disconnect();
      processor.disconnect();
      gain.disconnect();
    };
  };

  const start = async () => {
    stoppedRef.current = false;
    setError('');
    setTurns([]);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError('マイクを使うには HTTPS、または localhost で開いてください。');
      return;
    }
    const context = new AudioContext();
    audioContextRef.current = context;
    void context.resume();
    const cancelStart = (message: string) => {
      setError(message);
      void context.close();
      audioContextRef.current = null;
    };
    const token = await getIdToken();
    if (!token) {
      cancelStart('認証が必要です。再ログインしてください。');
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      cancelStart('マイクを利用できません。ブラウザの許可を確認してください。');
      return;
    }
    streamRef.current = stream;

    const api = import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT as string;
    const socket = new WebSocket(whisperLiveUrl(api));
    socketRef.current = socket;
    setActive(true);
    setStatus('OpenAI に接続しています。');

    socket.onopen = () => {
      if (stoppedRef.current) {
        socket.close();
        return;
      }
      socket.send(
        JSON.stringify({
          type: 'start',
          token,
          language,
          ...(caseTitle.trim() ? { caseTitle: caseTitle.trim() } : {}),
        }),
      );
    };
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') {
        return;
      }
      let message: { type?: string; message?: string; itemId?: string; text?: string };
      try {
        message = JSON.parse(event.data) as typeof message;
      } catch {
        return;
      }
      if (message.type === 'ready') {
        if (stoppedRef.current) {
          socket.close();
          return;
        }
        void startCapture(stream, context).then(() => {
          if (!stoppedRef.current) {
            setStatus('聞き取り中です。話し終わったら停止してください。');
          }
        });
        return;
      }
      if (message.type === 'delta' || message.type === 'transcript') {
        setTurns((current) => applyLiveMessage(current, message));
        return;
      }
      if (message.type === 'saved') {
        refreshHistories();
        const created = (message as { createdDate?: string }).createdDate;
        if (created) {
          onSaved?.(created);
        }
        return;
      }
      if (message.type === 'error') {
        setError(message.message || 'マイクの文字起こしに失敗しました。');
      }
    };
    socket.onerror = () => {
      setError('マイクの文字起こしに接続できませんでした。');
    };
    socket.onclose = () => {
      finish();
      socketRef.current = null;
    };
  };

  const stop = () => {
    stoppedRef.current = true;
    setStatus('停止しています。');
    sendJson({ type: 'stop' });
    stopCapture();
    window.setTimeout(() => {
      socketRef.current?.close();
    }, 8000);
  };

  if (enabled === false || (enabled === null && !shown)) {
    return null;
  }

  const transcript = liveTranscript(turns);

  return (
    <section
      className={embedded ? 'flex min-h-0 flex-1 flex-col gap-4' : 'mb-8 flex flex-col gap-4'}
      aria-labelledby='whisper-live-heading'
    >
      <h2 id='whisper-live-heading' className='sr-only'>
        マイクから（リアルタイム処理）
      </h2>
      <SupportText>マイクの音声はクラウドAI（海外リージョン）へ送信されます。</SupportText>
      {props.language === undefined ? (
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='whisper-live-language' size='lg'>
            言語
          </Label>
          <Select
            id='whisper-live-language'
            blockSize='md'
            value={language}
            disabled={active}
            onChange={(event) => setOwnLanguage(event.target.value)}
          >
            <option value='auto'>自動判定</option>
            <option value='ja'>日本語</option>
            <option value='en'>英語</option>
          </Select>
        </div>
      ) : null}
      <div className='flex flex-col items-start gap-3'>
        {active ? (
          <Button type='button' variant='outline' size='md' onClick={stop}>
            停止
          </Button>
        ) : (
          <Button type='button' variant='solid-fill' size='md' onClick={() => void start()}>
            マイクで開始
          </Button>
        )}
        {status ? <SupportText>{status}</SupportText> : null}
        {error ? <ErrorText>{error}</ErrorText> : null}
      </div>
      <pre
        aria-live='polite'
        className='min-h-24 flex-1 border border-solid-gray-420 bg-solid-gray-50 px-3 py-2 text-std-16N-170 whitespace-pre-wrap wrap-break-word'
      >
        {transcript ||
          (active ? '話し始めると、ここに文字が出ます。' : 'まだ文字起こしはありません。')}
      </pre>
      {embedded ? null : <Divider />}
    </section>
  );
};
