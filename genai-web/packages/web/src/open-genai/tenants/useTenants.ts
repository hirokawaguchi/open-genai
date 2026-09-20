import type { ListMyTenantsResponse, ListTenantMembersResponse, Tenant } from 'genai-web';
import useSWR, { useSWRConfig } from 'swr';
import { teamApi, teamApiFetcher } from '@/lib/fetcher';

export const MY_TENANTS_KEY = 'me/tenants';

export const useMyTenants = () => {
  const { data, isLoading, mutate, error } = useSWR<ListMyTenantsResponse>(
    MY_TENANTS_KEY,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  const tenants = data?.tenants ?? [];
  const isSystemAdmin = data?.isSystemAdmin ?? false;
  const orgTenants = tenants.filter((t) => t.kind !== 'shared');
  const grantedShared = tenants.filter((t) => t.kind === 'shared' && t.role === 'shared');
  const sharedForSwitcher = isSystemAdmin
    ? tenants.filter((t) => t.kind === 'shared')
    : grantedShared;
  return {
    tenants,
    orgTenants,
    grantedShared,
    switchableTenants: [...orgTenants, ...sharedForSwitcher],
    activeTenantId: data?.activeTenantId,
    isSystemAdmin,
    /** 別組織または共有棟の鍵がある人だけ切り替えを出す。オンプレ1組織では出さない */
    canSwitchTenants: orgTenants.length >= 2 || grantedShared.length > 0,
    /** 棟の管理者（スーパー管理者またはその棟の管理者）だけ管理画面を出す */
    canManageTenants: isSystemAdmin || tenants.some((t) => t.isAdmin),
    isLoading,
    error,
    mutate,
  };
};

export const useTenantActions = () => {
  const { mutate } = useSWRConfig();

  const revalidateTenantViews = async () => {
    await mutate(
      (key) => {
        if (typeof key !== 'string') return false;
        return (
          key === MY_TENANTS_KEY ||
          key === 'tenants' ||
          key === 'chats' ||
          key.startsWith('chats') ||
          key.startsWith('systemcontexts') ||
          key.startsWith('/systemcontexts') ||
          key.startsWith('teams') ||
          key.startsWith('knowledge') ||
          key.includes('exapps') ||
          key.includes('app-pins')
        );
      },
      undefined,
      { revalidate: true },
    );
  };

  return {
    setActive: async (tenantId: string) => {
      await teamApi.put('me/tenants/active', { tenantId });
      await revalidateTenantViews();
    },
    createTenant: async (tenantName: string, features?: Record<string, boolean>) => {
      const res = await teamApi.post<Tenant>('tenants', { tenantName, features });
      await revalidateTenantViews();
      return res.data;
    },
    updateTenant: async (
      tenantId: string,
      body: { tenantName?: string; features?: Record<string, boolean> },
    ) => {
      const res = await teamApi.put<Tenant>(`tenants/${tenantId}`, body);
      await revalidateTenantViews();
      return res.data;
    },
    deleteTenant: async (tenantId: string) => {
      await teamApi.delete(`tenants/${tenantId}`);
      await revalidateTenantViews();
    },
    listMembers: async (tenantId: string) => {
      const res = await teamApi.get<ListTenantMembersResponse>(`tenants/${tenantId}/members`);
      return res.data.members;
    },
    inviteMember: async (
      tenantId: string,
      email: string,
      opts?: { role?: string; isAdmin?: boolean },
    ) => {
      const res = await teamApi.post(`tenants/${tenantId}/members`, {
        email,
        role: opts?.role,
        isAdmin: opts?.isAdmin ?? false,
      });
      return res.data;
    },
    updateMember: async (
      tenantId: string,
      userId: string,
      body: { role?: string; isAdmin?: boolean },
    ) => {
      const res = await teamApi.put(`tenants/${tenantId}/members/${encodeURIComponent(userId)}`, body);
      return res.data;
    },
    removeMember: async (tenantId: string, userId: string) => {
      await teamApi.delete(`tenants/${tenantId}/members/${encodeURIComponent(userId)}`);
    },
    revalidateTenantViews,
  };
};
