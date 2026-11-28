import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { Markdown } from '@/components/Markdown';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ApiError, teamApi } from '@/lib/fetcher';
import { stageOfficeFile } from '@/open-genai/office/handoff';
import { officePathForFormat } from '@/open-genai/office/kinds';
import type { NotebookFile } from './types';

type OfficePreview = {
  kind: 'text' | 'sheets' | 'slides';
  note?: string;
  text?: string;
  sheets?: { name: string; rows: string[][] }[];
  slides?: { title: string; lines: string[] }[];
};

type Props = {
  sessionId: string;
  file: NotebookFile | null;
  onClose: () => void;
};

const extOf = (name: string) => name.toLowerCase().split('.').pop() || '';

const kindOf = (name: string) => {
  const ext = extOf(name);
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) return 'image' as const;
  if (ext === 'pdf') return 'pdf' as const;
  if (['docx', 'xlsx', 'pptx'].includes(ext)) return 'office' as const;
  if (['txt', 'md', 'csv', 'html', 'json'].includes(ext)) return 'text' as const;
  return 'other' as const;
};

const imageType = (name: string) => {
  const ext = extOf(name);
  if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg';
  if (ext === 'webp') return 'image/webp';
  if (ext === 'gif') return 'image/gif';
  return 'image/png';
};

const bytesFromBase64 = (content: string) => {
  const binary = atob(content);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
};

const officeOpenLabel = (name: string) => {
  const ext = extOf(name);
  if (ext === 'xlsx') return '表計算で開く';
  if (ext === 'pptx') return 'スライドで開く';
  return '文書で開く';
};

const errorText = (error: unknown) => {
  if (error instanceof ApiError) {
    const data = error.data as { error?: string } | undefined;
    if (data?.error) return data.error;
  }
  return 'ファイルを表示できませんでした。';
};

export const NotebookFilePreview = ({ sessionId, file, onClose }: Props) => {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [office, setOffice] = useState<OfficePreview | null>(null);
  const [kind, setKind] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState('');

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    let objectUrl = '';
    const nextKind = kindOf(file.filename);
    setBusy(true);
    setError('');
    setOpenError('');
    setOpening(false);
    setText('');
    setOffice(null);
    setUrl('');
    setKind(nextKind);
    void (async () => {
      try {
        if (nextKind === 'office') {
          const res = await teamApi.get<OfficePreview>(
            `notebook/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(file.id)}/preview`,
          );
          if (cancelled) return;
          setOffice(res.data);
          return;
        }
        if (nextKind === 'other') return;
        const res = await teamApi.get<{ filename: string; content: string }>(
          `notebook/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(file.id)}/content`,
        );
        if (cancelled) return;
        const content = res.data?.content ?? '';
        if (nextKind === 'text') {
          setText(new TextDecoder().decode(bytesFromBase64(content)));
          return;
        }
        const bytes = bytesFromBase64(content);
        const type = nextKind === 'pdf' ? 'application/pdf' : imageType(file.filename);
        objectUrl = URL.createObjectURL(new Blob([bytes], { type }));
        setUrl(objectUrl);
      } catch (caught) {
        if (!cancelled) setError(errorText(caught));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file, sessionId]);

  const markdown = extOf(file?.filename || '') === 'md' || text.includes('```mermaid');
  const openInOffice = async () => {
    if (!file || opening) return;
    const path = officePathForFormat(extOf(file.filename));
    if (!path) return;
    setOpening(true);
    setOpenError('');
    try {
      const res = await teamApi.get<{ filename: string; content: string }>(
        `notebook/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(file.id)}/content`,
      );
      const bytes = bytesFromBase64(res.data?.content ?? '');
      await stageOfficeFile(res.data?.filename || file.filename, bytes);
      onClose();
      navigate(`${path}?local=1`);
    } catch (caught) {
      setOpenError(errorText(caught));
      setOpening(false);
    }
  };

  return (
    <CustomDialog isOpen={!!file} onClose={onClose}>
      <CustomDialogPanel className='!max-w-5xl'>
        <CustomDialogHeader hasClose onClose={onClose}>
          {file?.filename || 'ファイル'}
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='flex flex-col gap-3 text-left'>
            {busy ? <p className='text-std-16N-170 text-solid-gray-700'>表示しています。</p> : null}
            {error ? (
              <p className='text-std-16N-170 text-error-1' role='alert'>
                {error}
              </p>
            ) : null}
            {kind === 'pdf' && url ? (
              <iframe
                title={file?.filename || 'PDF'}
                src={url}
                className='h-[70vh] w-full rounded-8 border border-solid-gray-300 bg-white'
              />
            ) : null}
            {kind === 'image' && url ? (
              <img
                alt={file?.filename || ''}
                src={url}
                className='max-h-[70vh] w-full object-contain'
              />
            ) : null}
            {kind === 'text' && !error && !busy ? (
              markdown ? (
                <div className='max-h-[70vh] overflow-auto rounded-8 border border-solid-gray-300 bg-white p-3'>
                  <Markdown>{text}</Markdown>
                </div>
              ) : (
                <pre className='max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-8 border border-solid-gray-300 bg-white p-3 text-std-16N-170 text-solid-gray-900'>
                  {text}
                </pre>
              )
            ) : null}
            {kind === 'office' && office?.kind === 'text' ? (
              <pre className='max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-8 border border-solid-gray-300 bg-white p-3 text-std-16N-170 text-solid-gray-900'>
                {office.text}
              </pre>
            ) : null}
            {kind === 'office' && office?.kind === 'sheets'
              ? office.sheets?.map((sheet) => (
                  <div
                    key={sheet.name}
                    className='max-h-[70vh] overflow-auto rounded-8 border border-solid-gray-300'
                  >
                    <p className='sticky top-0 bg-solid-gray-50 px-3 py-2 text-std-16B-150 text-solid-gray-900'>
                      {sheet.name}
                    </p>
                    <table className='w-full border-collapse text-dns-14N-130'>
                      <tbody>
                        {sheet.rows.map((row, index) => (
                          <tr key={index} className='border-t border-solid-gray-200'>
                            {row.map((cell, cellIndex) => (
                              <td key={cellIndex} className='px-2 py-1 align-top text-solid-gray-900'>
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              : null}
            {kind === 'office' && office?.kind === 'slides'
              ? office.slides?.map((slide, index) => (
                  <section key={`${slide.title}-${index}`} className='rounded-8 border border-solid-gray-300 p-3'>
                    <h3 className='text-std-16B-150 text-solid-gray-900'>{slide.title}</h3>
                    {slide.lines.map((line, lineIndex) => (
                      <p
                        key={`${index}-${lineIndex}`}
                        className='mt-1 whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'
                      >
                        {line}
                      </p>
                    ))}
                  </section>
                ))
              : null}
            {kind === 'office' && office?.note ? (
              <p className='text-dns-14N-130 text-solid-gray-600'>{office.note}</p>
            ) : null}
            {kind === 'office' ? (
              <div className='flex flex-col items-end gap-2'>
                {openError ? (
                  <p className='text-dns-14N-130 text-error-1' role='alert'>
                    {openError}
                  </p>
                ) : null}
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={opening || undefined}
                  onClick={() => void openInOffice()}
                >
                  {opening ? '開いています...' : officeOpenLabel(file?.filename || '')}
                </Button>
              </div>
            ) : null}
            {kind === 'other' ? (
              <p className='text-std-16N-170 text-solid-gray-700'>この形式は画面では表示できません。</p>
            ) : null}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
