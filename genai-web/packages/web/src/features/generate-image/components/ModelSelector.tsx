import { CustomSelect } from '@/components/ui/CustomSelect';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { findModelDisplayNameByModelId } from '@/models';

export const ModelSelector = () => {
  const { selectedModelId, setSelectedModelId, availableModelIds: modelIds } = useSelectedModel();

  return (
    <CustomSelect
      label='AIモデル：'
      value={selectedModelId}
      onChange={setSelectedModelId}
      options={modelIds.map((m) => ({
        value: m,
        label: findModelDisplayNameByModelId(m),
      }))}
    />
  );
};
