import { useEffect } from 'react';
import {
  FileUploadViewportOverlay,
  FileUploadViewportOverlayMessage,
  useFileDrop,
} from '@/components/ui/dads/FileUpload';
import { useChatStore } from '@/features/chat/stores/useChatStore';
import { useFiles } from '@/hooks/useFiles';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { FILE_LIMIT } from '../constants';

type Props = {
  fileUpload: boolean;
  accept: string[];
};

export const FileDrop = (props: Props) => {
  const { fileUpload, accept } = props;

  const { isDragOver, setIsDragOver } = useChatStore();

  const { usecase } = useUsecasePath();
  const { uploadFiles } = useFiles(usecase);

  const {
    announcerText,
    announcerAssertiveText,
    handleViewportDragEnter,
    handleViewportDragOver,
    handleViewportDragLeave,
    handleViewportDrop,
  } = useFileDrop({
    droppable: true,
    dropAreaExpandable: true,
    onFilesAdded: (files) => {
      uploadFiles(files, FILE_LIMIT, accept);
    },
  });

  // isDragOver が true になったときにアナウンスを開始
  // isDragOver の変化時のみ実行したいため依存配列から除外
  useEffect(() => {
    if (isDragOver && fileUpload) {
      handleViewportDragEnter();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDragOver, fileUpload]);

  // ファイルドラッグ時にオーバーレイを非表示
  const handleDragLeave = () => {
    handleViewportDragLeave();
    setIsDragOver(false);
  };

  const handleDragOver = (event: React.DragEvent) => {
    handleViewportDragOver(event);
  };

  // ファイルドロップ時にファイルを追加
  const handleDrop = (event: React.DragEvent) => {
    handleViewportDrop(event);
    setIsDragOver(false);
  };

  return (
    <>
      <div className='sr-only' aria-live='polite'>
        {announcerText}
      </div>
      <div className='sr-only' aria-live='assertive'>
        {announcerAssertiveText}
      </div>

      {isDragOver && fileUpload && (
        <FileUploadViewportOverlay
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <FileUploadViewportOverlayMessage>
            <span className='inline-block'>ファイルをドロップして</span>
            <span className='inline-block'>アップロード</span>
          </FileUploadViewportOverlayMessage>
        </FileUploadViewportOverlay>
      )}
    </>
  );
};
