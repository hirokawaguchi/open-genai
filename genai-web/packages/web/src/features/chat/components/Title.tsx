import { Menu, MenuButton, MenuItem, MenuItems } from '@headlessui/react';
import { useEffect, useRef, useState } from 'react';
import { PiPencilLine, PiTrash } from 'react-icons/pi';
import { useNavigate } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { MoreVertIcon } from '@/components/ui/icons/MoreVertIcon';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/Tooltip';
import { DialogConfirmDeleteChat } from '@/features/chat/components/DialogConfirmDeleteChat';
import { useChat } from '@/hooks/useChat';
import { useChatList } from '@/hooks/useChatList';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { focus } from '@/utils/focus';

type Props = {
  title: string;
};

export const Title = (props: Props) => {
  const { title } = props;

  const { usecase, chatId } = useUsecasePath();
  const { loadingMessages, isEmpty } = useChat(usecase, chatId);
  const { updateChatTitle, deleteChat } = useChatList();

  const [openDeleteDialog, setOpenDeleteDialog] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [tempTitle, setTempTitle] = useState(title);
  const [isDeleting, setIsDeleting] = useState(false);

  const editInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing) {
      editInputRef.current?.focus();
    }
  }, [isEditing]);

  const handleFocusAfterEditing = async () => {
    setIsEditing(false);
    focus(`${chatId}-menu-button`);
  };

  const navigate = useNavigate();
  const onDeleteChat = async (_chatId: string) => {
    setIsDeleting(true);
    try {
      if (_chatId !== '') {
        await deleteChat(_chatId);
        navigate('/chat');
      } else {
        throw new Error('Chat IDが指定されていません');
      }
    } catch {
      console.error('エラーが発生したため会話を削除できませんでした');
    } finally {
      setIsDeleting(false);
      setOpenDeleteDialog(false);
    }
  };

  const handleUpdateTitle = async (title?: string) => {
    if (!chatId) return;
    try {
      await updateChatTitle(chatId, title ?? tempTitle);
      handleFocusAfterEditing();
    } catch {
      handleFocusAfterEditing();
    }
  };

  const handleEditingCancel = () => {
    handleFocusAfterEditing();
  };

  const handleEditingKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleUpdateTitle(e.currentTarget.value);
    }

    if (e.key === 'Escape') {
      e.preventDefault();
      handleEditingCancel();
    }
  };

  return (
    <>
      {!isEditing && (
        <div className='flex items-start gap-x-1'>
          <h1 className='flex items-center justify-start text-std-20B-150 h-min min-h-9 text-pretty lg:text-std-24B-150 print:visible print:my-5 print:h-min'>
            {title}
          </h1>
          {!isEmpty && !loadingMessages && chatId && (
            <div className='group relative ml-1 flex-none mt-0.5'>
              <Menu>
                <Tooltip placement='bottom'>
                  <TooltipTrigger asChild>
                    <MenuButton
                      id={`${chatId}-menu-button`}
                      className={`flex size-9 items-center justify-center rounded-4 after:absolute after:-inset-full after:m-auto after:h-11 after:w-11 hover:bg-solid-gray-50 hover:-outline-offset-[calc(2/16*1rem)] hover:outline-black hover:outline-solid focus-visible:bg-yellow-300 focus-visible:ring-[calc(6/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-black focus-visible:outline-solid focus-visible:ring-inset`}
                    >
                      <MoreVertIcon aria-label='チャットの操作' role='img' className='lg:mt-0.5' />
                    </MenuButton>
                  </TooltipTrigger>
                  <TooltipContent aria-hidden={true}>チャットの操作</TooltipContent>
                </Tooltip>

                <MenuItems
                  modal={false}
                  className={`absolute top-full right-0 z-10 w-auto min-w-fit rounded-8 border border-solid-gray-420 bg-white py-2 shadow-1 focus:outline-hidden`}
                >
                  <MenuItem>
                    {({ focus }) => (
                      <button
                        type='button'
                        onClick={() => {
                          setTempTitle(title);
                          setIsEditing(true);
                        }}
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiPencilLine aria-hidden={true} className='text-lg' />
                        チャット名を変更
                      </button>
                    )}
                  </MenuItem>
                  <MenuItem>
                    {({ focus }) => (
                      <button
                        type='button'
                        onClick={() => {
                          setOpenDeleteDialog(true);
                        }}
                        aria-haspopup='dialog'
                        className={`relative flex w-full items-center gap-x-2 bg-white py-3 pr-6 pl-3 text-oln-16N-100 text-nowrap text-error-1 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] ${focus ? '[:root[data-headlessui-focus-visible]_&]:bg-yellow-300 [:root[data-headlessui-focus-visible]_&]:text-solid-gray-800 [:root[data-headlessui-focus-visible]_&]:ring-[calc(6/16*1rem)] [:root[data-headlessui-focus-visible]_&]:ring-yellow-300 [:root[data-headlessui-focus-visible]_&]:outline-4 [:root[data-headlessui-focus-visible]_&]:-outline-offset-4 [:root[data-headlessui-focus-visible]_&]:outline-black [:root[data-headlessui-focus-visible]_&]:outline-solid [:root[data-headlessui-focus-visible]_&]:ring-inset' : ''}`}
                      >
                        <PiTrash aria-hidden={true} className='text-lg' />
                        チャットを削除
                      </button>
                    )}
                  </MenuItem>
                </MenuItems>
              </Menu>
            </div>
          )}
        </div>
      )}

      {isEditing && (
        <div className='grid w-fit grid-cols-[1fr_auto] grid-rows-[auto] max-w-[calc(1056/16*1rem)] items-center justify-start py-0 pr-0 pl-1'>
          <div className='relative min-w-0 pr-4'>
            <span
              aria-hidden={true}
              className='invisible flex max-w-full items-center justify-start overflow-hidden text-std-20B-150 min-h-9 text-nowrap lg:text-std-24B-150'
            >
              {tempTitle}
            </span>
            <Input
              ref={editInputRef}
              type='text'
              blockSize='sm'
              className='absolute -inset-x-1 inset-y-0 text-std-18N-160 leading-100! lg:-inset-x-4'
              value={tempTitle}
              aria-label='チャット名を変更'
              onChange={(e) => {
                setTempTitle(e.target.value);
              }}
              onKeyDown={handleEditingKeyDown}
            />
          </div>
          <div className='flex flex-none flex-row-reverse justify-start gap-x-1.5 pr-1 pl-2'>
            <Button variant='solid-fill' size='sm' onClick={() => handleUpdateTitle()}>
              確定
            </Button>

            <Button variant='text' size='xs' onClick={handleEditingCancel}>
              キャンセル
            </Button>
          </div>
        </div>
      )}

      {chatId && (
        <DialogConfirmDeleteChat
          isOpen={openDeleteDialog}
          isDeleting={isDeleting}
          chatId={chatId}
          onDelete={() => {
            onDeleteChat(chatId);
          }}
          onClose={() => setOpenDeleteDialog(false)}
        />
      )}
    </>
  );
};
