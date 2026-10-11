import { useEffect, useState } from 'react';
import { PiCheckBold, PiSpinnerGap } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { FilePickButton } from '@/open-genai/patchform/runtime/FilePickButton';
import { useLmsActions, type MaterialUploadProgress } from './useLms';

const inputClass = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';

const steps = ['name', 'file'] as const;
type StepId = (typeof steps)[number];

const stepTitle: Record<StepId, string> = {
  name: '名前を決める',
  file: 'ファイルを選ぶ',
};

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
};

const fileKind = (file: File | null): 'video' | 'slides' | null => {
  if (!file) {
    return null;
  }
  const name = file.name.toLowerCase();
  if (name.endsWith('.pdf')) {
    return 'slides';
  }
  if (name.endsWith('.mp4') || name.endsWith('.webm')) {
    return 'video';
  }
  return null;
};

export const MaterialWizard = ({ open, onClose, onCreated }: Props) => {
  const actions = useLmsActions();
  const [step, setStep] = useState<StepId>('name');
  const [title, setTitle] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<MaterialUploadProgress | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setStep('name');
    setTitle('');
    setFile(null);
    setProgress(null);
    setLocalError(null);
    actions.setError(null);
  }, [open, actions.setError]);

  const stepIndex = steps.indexOf(step);
  const kind = fileKind(file);
  const shownError = localError || actions.error;

  const goBack = () => {
    if (actions.busy) {
      return;
    }
    setLocalError(null);
    const previous = steps[stepIndex - 1];
    if (previous) {
      setStep(previous);
    }
  };

  const goNext = () => {
    setLocalError(null);
    if (!title.trim()) {
      setLocalError('名前を入力してください。');
      return;
    }
    setStep('file');
  };

  const place = async () => {
    if (actions.busy) {
      return;
    }
    setLocalError(null);
    if (!title.trim()) {
      setLocalError('名前を入力してください。');
      setStep('name');
      return;
    }
    if (!file || !kind) {
      setLocalError('動画は mp4 または webm、テキストは PDF を選んでください。');
      return;
    }
    const saved = await actions.uploadMaterial(file, title.trim(), setProgress);
    if (!saved) {
      setProgress(null);
      return;
    }
    onCreated();
    onClose();
  };

  return (
    <CustomDialog isOpen={open} onClose={actions.busy ? () => undefined : onClose} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={actions.busy ? () => undefined : onClose}>
          教材を置く
        </CustomDialogHeader>
        <CustomDialogBody>
          <p className='text-dns-16N-130 text-solid-gray-600'>
            手順 {stepIndex + 1} / {steps.length}　{stepTitle[step]}
          </p>
          <p className='mt-1 text-std-16N-170 text-solid-gray-700'>
            {step === 'name'
              ? '教材一覧に出る名前です。ファイルは次の手順で選びます。'
              : '動画は mp4 または webm、テキストは PDF です。'}
          </p>

          {step === 'name' && (
            <div className='mt-4'>
              <Label htmlFor='lms-material-title' size='sm'>
                名前
              </Label>
              <input
                id='lms-material-title'
                className={inputClass}
                value={title}
                placeholder='例：情報セキュリティの基礎'
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
          )}

          {step === 'file' && (
            <div className='mt-4'>
              <Label htmlFor='lms-material-file' size='sm'>
                ファイル
              </Label>
              <FilePickButton
                id='lms-material-file'
                accept='.mp4,.webm,.pdf,video/mp4,video/webm,application/pdf'
                filename={file?.name}
                disabled={actions.busy}
                busy={progress?.phase === 'upload'}
                busyLabel='送信しています'
                onFile={(next) => {
                  setFile(next);
                  setLocalError(null);
                }}
              />
              {file && !progress && kind === 'video' && (
                <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>動画として置きます。</p>
              )}
              {file && !progress && kind === 'slides' && (
                <p className='mt-2 text-dns-14N-130 text-solid-gray-600'>テキストとして置きます。</p>
              )}
              {progress && <UploadStatus progress={progress} kind={kind} />}
            </div>
          )}

          {shownError && (
            <p className='mt-4 text-dns-16N-130 text-error-1' role='alert'>
              {shownError}
            </p>
          )}

          <div className='mt-6 flex flex-wrap items-center justify-between gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={step === 'name' || actions.busy}
              onClick={goBack}
            >
              戻る
            </Button>
            {step === 'file' ? (
              <LoadingButton
                type='button'
                variant='solid-fill'
                size='md'
                loading={actions.busy}
                disabled={!file || !kind}
                onClick={() => void place()}
              >
                教材庫に置く
              </LoadingButton>
            ) : (
              <Button type='button' variant='solid-fill' size='md' onClick={goNext}>
                次へ
              </Button>
            )}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};

const phaseRank = (phase: MaterialUploadProgress['phase'], slides: boolean) => {
  if (phase === 'prepare' || phase === 'upload') {
    return 0;
  }
  if (phase === 'convert') {
    return 1;
  }
  return slides ? 2 : 1;
};

const UploadStatus = ({
  progress,
  kind,
}: {
  progress: MaterialUploadProgress;
  kind: 'video' | 'slides' | null;
}) => {
  const slides = kind === 'slides';
  const stages = [
    { label: 'ファイルを送る' },
    ...(slides ? [{ label: 'ページ画像にする' }] : []),
    { label: '教材庫に登録する' },
  ];
  const current = phaseRank(progress.phase, slides);
  return (
    <div className='mt-4 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4' role='status' aria-live='polite'>
      <div className='flex items-start gap-3'>
        <PiSpinnerGap aria-hidden={true} className='mt-0.5 size-6 shrink-0 animate-spin text-blue-900' />
        <div className='min-w-0'>
          <p className='text-std-16B-150 text-solid-gray-900'>{progress.label}</p>
          <p className='mt-1 text-dns-14N-130 text-solid-gray-700'>{progress.detail}</p>
        </div>
      </div>
      <div className='mt-3 h-2 overflow-hidden rounded-full bg-solid-gray-200'>
        <div
          className={`h-full rounded-full bg-blue-900 ${progress.percent == null ? 'w-1/3 animate-pulse' : ''}`}
          style={progress.percent == null ? undefined : { width: `${progress.percent}%` }}
        />
      </div>
      <ol className='mt-3 flex flex-col gap-1'>
        {stages.map((stage, index) => {
          const done = index < current || (progress.percent === 100 && index === current);
          const active = index === current && progress.percent !== 100;
          return (
            <li key={stage.label} className='flex items-center gap-2 text-dns-14N-130'>
              {done ? (
                <PiCheckBold aria-hidden={true} className='size-4 text-blue-900' />
              ) : active ? (
                <PiSpinnerGap aria-hidden={true} className='size-4 animate-spin text-blue-900' />
              ) : (
                <span aria-hidden={true} className='inline-block size-4 rounded-full border border-solid-gray-420' />
              )}
              <span className={active || done ? 'text-solid-gray-900' : 'text-solid-gray-600'}>{stage.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
