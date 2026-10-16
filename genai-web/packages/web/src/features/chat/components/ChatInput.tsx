import { zodResolver } from '@hookform/resolvers/zod';
import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { PiSpinnerGap } from 'react-icons/pi';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import {
  FileUpload,
  FileUploadFileInfo,
  FileUploadFileItem,
  FileUploadFileList,
  FileUploadFileMarker,
  FileUploadFileMeta,
  FileUploadFileName,
  FileUploadInput,
} from '@/components/ui/dads/FileUpload';
import { formatSize } from '@/components/ui/dads/FileUpload/utils/formatSize';
import { AttachmentIcon } from '@/components/ui/icons/AttachmentIcon';
import { SendIcon } from '@/components/ui/icons/SendIcon';
import { SupportText } from '@/components/ui/dads/SupportText';
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useFiles } from '@/hooks/useFiles';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { useSubmitKey } from '@/hooks/useSubmitKey';
import { requestSubmitOnEnter } from '@/utils/keyboard';
import { FILE_LIMIT } from '../constants';
import { ChatFormSchema, chatFormSchema } from '../schema';

type Props = {
  onSend: (content?: string) => void;
  fileUpload: boolean;
  accept: string[];
};

export const ChatInput = (props: Props) => {
  const { onSend, fileUpload, accept } = props;
  const { hint } = useSubmitKey();

  const { usecase, chatId } = useUsecasePath();
  const { content, setContent, hasSent, setHasSent } = useChatStore();

  const { loading, stopGeneration } = useChat(usecase, chatId);
  const {
    uploadedFiles,
    uploadFiles,
    checkFiles,
    deleteUploadedFile,
    dropPendingFile,
    uploading,
    errorMessages,
  } = useFiles(usecase);

  const isInitialChat = !chatId && !hasSent;

  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachButtonRef = useRef<HTMLButtonElement>(null);

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<ChatFormSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(chatFormSchema),
    values: {
      content,
    },
  });

  useEffect(() => {
    checkFiles(FILE_LIMIT, accept);
  }, [checkFiles, accept]);

  const onChangeFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) {
      return;
    }

    uploadFiles(Array.from(files), FILE_LIMIT, accept);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const deleteFile = async (fileUrl: string, idx: number) => {
    if (!fileUrl) {
      dropPendingFile(idx);
      attachButtonRef.current?.focus();
      return;
    }
    const remainingCount = uploadedFiles.filter((f) => f.s3Url !== fileUrl).length;
    await deleteUploadedFile(fileUrl, FILE_LIMIT, accept);
    if (remainingCount === 0) {
      attachButtonRef.current?.focus();
    } else if (idx < remainingCount) {
      document.getElementById(`attached-file-${idx}-remove`)?.focus();
    } else {
      document.getElementById(`attached-file-${remainingCount - 1}-remove`)?.focus();
    }
  };

  const handlePaste = async (pasteEvent: React.ClipboardEvent) => {
    const fileList = pasteEvent.clipboardData.items || [];
    const files = Array.from(fileList)
      .filter((file) => file.kind === 'file')
      .map((file) => file.getAsFile() as File);

    if (files.length > 0) {
      uploadFiles(Array.from(files), FILE_LIMIT, accept);
      pasteEvent.preventDefault();
    }
  };

  const handleClickFileUpload = () => {
    if (uploading) {
      return;
    }
    fileInputRef.current?.click();
  };

  const [fileErrorMessage, setFileErrorMessage] = useState('');
  const [uploadNotice, setUploadNotice] = useState('');
  const pendingSendRef = useRef<string | null>(null);
  const disabledSend = loading;
  const fileErrorText = '選択したファイルにエラーがあります。該当ファイルをチェックしてください。';

  useEffect(() => {
    if (errorMessages.length === 0) {
      setFileErrorMessage('');
    }
  }, [errorMessages]);

  const deliver = (text: string) => {
    pendingSendRef.current = null;
    setUploadNotice('');
    setFileErrorMessage('');
    setContent(text);
    setHasSent(true);
    onSend(text);
  };

  const onSubmit = handleSubmit((data) => {
    if (disabledSend) {
      return;
    }

    if (errorMessages.length > 0) {
      pendingSendRef.current = null;
      setUploadNotice('');
      setFileErrorMessage(fileErrorText);
      return;
    }

    // アップロード中はボタンを無効にせず、完了後に送る。
    // ここで黙って return すると、青い送信ボタンを押しても何も起きない。
    if (uploading) {
      pendingSendRef.current = data.content;
      setUploadNotice('ファイルのアップロードが終わり次第、送信します。');
      return;
    }

    deliver(data.content);
  });

  useEffect(() => {
    const text = pendingSendRef.current;
    if (text == null || uploading || loading) {
      return;
    }
    if (errorMessages.length > 0) {
      pendingSendRef.current = null;
      setUploadNotice('');
      setFileErrorMessage(fileErrorText);
      return;
    }
    pendingSendRef.current = null;
    setUploadNotice('');
    setFileErrorMessage('');
    setContent(text);
    setHasSent(true);
    onSend(text);
  }, [uploading, loading, errorMessages, onSend, setContent, setHasSent]);

  return (
    <div
      className={`
        relative flex flex-col pb-2 border-t border-t-solid-gray-800 items-center justify-center bg-white print:hidden
      `}
    >
      <form className='w-full' onSubmit={onSubmit} aria-labelledby='chat-input-heading'>
        <h2 id='chat-input-heading' className='sr-only'>
          {isInitialChat
            ? '調べたいことやお困りごとなど、何でも入力してみましょう'
            : '追加で質問や不明点などあれば返答してみましょう'}
        </h2>
        <SupportText id='chat-input-submit-hint' className='mb-1'>
          {hint}
        </SupportText>
        <div className='relative flex items-end bg-white'>
          <div className='flex w-full flex-col gap-2'>
            <AutoResizeTextarea
              id='chat-input'
              className='resize-none'
              rows={isInitialChat ? 2 : 1}
              required
              placeholder={
                isInitialChat
                  ? '調べたいことやお困りごとなど、何でも入力してみましょう'
                  : '追加で質問や不明点などあれば返答してみましょう'
              }
              aria-labelledby='chat-input-heading'
              aria-describedby='chat-input-submit-hint chat-input-error chat-input-file-error'
              onPaste={fileUpload ? handlePaste : undefined}
              onKeyDown={requestSubmitOnEnter}
              {...register('content', {
                onChange: (e) => {
                  setValue('content', e.target.value);
                  setContent(e.target.value);
                },
              })}
            />
            {(errors.content || fileErrorMessage) && (
              <ul className='p-0 list-none space-y-0.5'>
                {errors.content && (
                  <li>
                    <ErrorText id='chat-input-error'>＊{errors.content.message}</ErrorText>
                  </li>
                )}
                {fileErrorMessage && (
                  <li>
                    <ErrorText id='chat-input-file-error'>＊{fileErrorMessage}</ErrorText>
                  </li>
                )}
              </ul>
            )}

            <div className='flex w-full flex-col gap-2'>
              <div className='flex w-full items-start gap-6'>
              {fileUpload && (
                <FileUpload className='min-w-0 flex-1' hasError={errorMessages.length > 0}>
                  <FileUploadInput
                    ref={fileInputRef}
                    onChange={onChangeFiles}
                    accept={accept?.join(',')}
                    multiple
                  />
                  <Button
                    ref={attachButtonRef}
                    variant='outline'
                    type='button'
                    size='md'
                    aria-describedby='chat-input-file-error'
                    aria-disabled={uploading || undefined}
                    aria-busy={uploading || undefined}
                    className='inline-flex justify-center items-center gap-1 group-data-[has-error=true]/file-upload:border-error-1'
                    title={uploading ? 'ファイルをアップロードしています' : '4.5MBまで'}
                    onClick={handleClickFileUpload}
                  >
                    {uploading ? (
                      <PiSpinnerGap aria-hidden={true} className='size-4 shrink-0 animate-spin' />
                    ) : (
                      <AttachmentIcon aria-hidden={true} className='shrink-0' />
                    )}
                    ファイルを添付
                  </Button>
                </FileUpload>
              )}

              <LoadingButton
                type={loading ? 'button' : 'submit'}
                variant='solid-fill'
                size='md'
                disabled={loading ? false : disabledSend}
                onClick={
                  loading
                    ? (event) => {
                        event.preventDefault();
                        stopGeneration();
                      }
                    : undefined
                }
                className='relative z-10 shrink-0 ml-auto inline-flex justify-center items-center gap-1 min-w-36'
              >
                <SendIcon aria-hidden={true} className='shrink-0' />
                {loading ? '中止' : '送信'}
              </LoadingButton>
              </div>

              {fileUpload && uploadedFiles.length > 0 && (
                <FileUpload className='w-full' hasError={errorMessages.length > 0}>
                  <FileUploadFileList className='py-1 overflow-y-auto max-h-48 overscroll-contain [scrollbar-gutter:stable]'>
                      {uploadedFiles.map((uploadedFile, idx) => (
                        <FileUploadFileItem
                          key={idx}
                          hasError={uploadedFile.errorMessages.length > 0}
                          aria-busy={uploadedFile.uploading || undefined}
                        >
                          <FileUploadFileMarker />
                          <FileUploadFileInfo>
                            <p>
                              <FileUploadFileName id={`attached-file-${idx}-name`}>
                                {uploadedFile.name}
                              </FileUploadFileName>
                              <FileUploadFileMeta>
                                <span>{formatSize(uploadedFile.file.size)}</span>（
                                <span>
                                  {Math.ceil((uploadedFile.file.size * 4) / 3).toLocaleString()}
                                </span>
                                バイト）
                              </FileUploadFileMeta>
                              {uploadedFile.uploading && (
                                <span className='ml-2 inline-flex items-center gap-1 text-solid-gray-600'>
                                  <PiSpinnerGap
                                    aria-hidden={true}
                                    className='size-4 shrink-0 animate-spin'
                                  />
                                  アップロード中
                                </span>
                              )}
                            </p>
                            {uploadedFile.errorMessages.length > 0 &&
                              uploadedFile.errorMessages.map((error) => (
                                <p key={error}>＊{error}</p>
                              ))}
                            {uploadedFile.piiWarned && (
                              <div className='text-orange-800 whitespace-pre-wrap'>
                                <p>
                                  ＊
                                  {(uploadedFile.piiMessage || '').split('\n')[0] ||
                                    `個人情報の可能性: ${(uploadedFile.piiCategories ?? []).join('・')}`}
                                </p>
                                {(uploadedFile.piiHits ?? []).length > 0 ? (
                                  <ul className='mt-1 list-disc pl-5 text-dns-14N-130'>
                                    {(uploadedFile.piiHits ?? []).slice(0, 6).map((h, i) => (
                                      <li key={`${h.category}-${h.offset ?? i}-${h.match}`}>
                                        {h.category}: 「{h.context || h.match}」
                                      </li>
                                    ))}
                                  </ul>
                                ) : (
                                  (uploadedFile.piiMessage || '')
                                    .split('\n')
                                    .slice(1)
                                    .filter(Boolean)
                                    .map((line) => (
                                      <p key={line} className='text-dns-14N-130'>
                                        {line}
                                      </p>
                                    ))
                                )}
                              </div>
                            )}
                          </FileUploadFileInfo>
                          <Button
                            id={`attached-file-${idx}-remove`}
                            type='button'
                            variant='text'
                            size='xs'
                            className='-order-1 shrink-0 min-w-14 min-h-[calc(30/16*1rem)] text-oln-16B-100'
                            onClick={() => {
                              if (uploadedFile.deleting) return;
                              deleteFile(uploadedFile.s3Url ?? '', idx);
                            }}
                            aria-labelledby={
                              uploadedFile.deleting
                                ? undefined
                                : `attached-file-${idx}-remove attached-file-${idx}-name`
                            }
                          >
                            {uploadedFile.deleting ? '解除中' : '解除'}
                          </Button>
                        </FileUploadFileItem>
                      ))}
                    </FileUploadFileList>
                </FileUpload>
              )}
              {uploadNotice && (
                <p className='m-0 text-dns-14N-130 text-solid-gray-600' role='status'>
                  {uploadNotice}
                </p>
              )}
            </div>
          </div>
        </div>
      </form>
    </div>
  );
};
