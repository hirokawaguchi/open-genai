import { CustomSelect } from '@/components/ui/CustomSelect';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { findModelDisplayNameByModelId } from '@/models';

export const ModelSelector = () => {
  const { selectedModelId, setSelectedModelId, availableModelIds: availableModels } = useSelectedModel();

  return (
    <div className='flex w-full'>
      <CustomSelect
        label='AIモデル：'
        buttonClassName='min-w-[calc(196/16*1rem)]'
        value={selectedModelId}
        onChange={setSelectedModelId}
        options={availableModels.map((m) => ({
          value: m,
          label: findModelDisplayNameByModelId(m),
        }))}
      />
    </div>
  );
};
