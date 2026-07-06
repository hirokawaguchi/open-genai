import { zodResolver } from '@hookform/resolvers/zod';
import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
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
import { LoadingButton } from '@/components/ui/LoadingButton';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useChat } from '@/hooks/useChat';
import { useFiles } from '@/hooks/useFiles';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { isSubmitKey } from '@/utils/keyboard';
import { FILE_LIMIT } from '../constants';
import { ChatFormSchema, chatFormSchema } from '../schema';

type Props = {
  onSend: () => void;
  fileUpload: boolean;
  accept: string[];
};

export const ChatInput = (props: Props) => {
  const { onSend, fileUpload, accept } = props;

  const { usecase, chatId } = useUsecasePath();
  const { content, setContent, hasSent, setHasSent } = useChatStore();

  const { loading } = useChat(usecase, chatId);
  const { uploadedFiles, uploadFiles, checkFiles, deleteUploadedFile, uploading, errorMessages } =
    useFiles(usecase);

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
  const disabledSend = loading;

  useEffect(() => {
    if (errorMessages.length === 0) {
      setFileErrorMessage('');
    }
  }, [errorMessages]);

  const onSubmit = handleSubmit((data) => {
    if (disabledSend) {
      return;
    }

    if (uploading) {
      return;
    }

    if (errorMessages.length > 0) {
      setFileErrorMessage(
        '選択したファイルにエラーがあります。該当ファイルをチェックしてください。',
      );
      return;
    }

    setFileErrorMessage('');
    setContent(data.content);
    setHasSent(true);
    onSend();
  });

  return (
    <div
      className={`
        relative flex flex-col pb-2 border-t border-t-solid-gray-800 items-center justify-center bg-white print:hidden
      `}
    >
      <form className='w-full' onSubmit={onSubmit} aria-labelledby='chat-input-heading'>
        <h2 id='chat-input-heading' className='self-start my-1 text-std-16N-170'>
          {isInitialChat
            ? '調べたいことやお困りごとなど、何でも入力してみましょう'
            : '追加で質問や不明点などあれば返答してみましょう'}
        </h2>
        <div className='relative flex items-end bg-white'>
          <div className='flex w-full flex-col gap-2'>
            <AutoResizeTextarea
              id='chat-input'
              className='resize-none'
              rows={isInitialChat ? 3 : 1}
              required
              placeholder=''
              aria-labelledby='chat-input-heading'
              aria-describedby='chat-input-error chat-input-file-error'
              onPaste={fileUpload ? handlePaste : undefined}
              onKeyDown={(e) => {
                if (isSubmitKey(e)) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
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

            <div className='flex w-full justify-start items-start gap-6'>
              {fileUpload && (
                <FileUpload className='flex-1' hasError={errorMessages.length > 0}>
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
                    className='inline-flex justify-center items-center gap-1 group-data-[has-error=true]/file-upload:border-error-1'
                    onClick={handleClickFileUpload}
                  >
                    <AttachmentIcon aria-hidden={true} className='shrink-0' />
                    添付するファイルを選択（4.5MBまで）
                  </Button>

                  {uploadedFiles.length > 0 && (
                    <FileUploadFileList className='mt-2! py-2 pl-2 overflow-y-auto max-h-48 -ml-2 -mr-[calc(168/16*1rem)] overscroll-contain [scrollbar-gutter:stable]'>
                      {uploadedFiles.map((uploadedFile, idx) => (
                        <FileUploadFileItem
                          key={idx}
                          hasError={uploadedFile.errorMessages.length > 0}
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
                            </p>
                            {uploadedFile.errorMessages.length > 0 &&
                              uploadedFile.errorMessages.map((error) => (
                                <p key={error}>＊{error}</p>
                              ))}
                          </FileUploadFileInfo>
                          <Button
                            id={`attached-file-${idx}-remove`}
                            type='button'
                            variant='text'
                            size='xs'
                            className='-order-1 shrink-0 min-w-14 min-h-[calc(30/16*1rem)] text-oln-16B-100'
                            onClick={() => {
                              if (uploadedFile.uploading || uploadedFile.deleting) return;
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
                  )}
                </FileUpload>
              )}

              <LoadingButton
                type='submit'
                variant='solid-fill'
                size='md'
                disabled={disabledSend}
                onClick={() => {}}
                className='shrink-0 ml-auto inline-flex justify-center items-center gap-1 min-w-36'
              >
                <SendIcon aria-hidden={true} className='shrink-0' />
                {loading ? '生成中...' : '送信'}
              </LoadingButton>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
};
