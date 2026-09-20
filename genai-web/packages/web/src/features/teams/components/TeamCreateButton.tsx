import { Link } from 'react-router';
import { Button } from '@/components/ui/dads/Button';
import { useMyTenants } from '@/open-genai/tenants/useTenants';
import { useTeamAuth } from '../hooks/useTeamAuth';

export const TeamCreateButton = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const { canManageTenants } = useMyTenants();
  const canCreateTeam = isSystemAdminGroup || canManageTenants;

  return (
    <>
      {canCreateTeam && (
        <div className='pt-2'>
          <Button
            asChild
            className='inline-flex justify-center items-center gap-2 w-48'
            variant='outline'
            size='lg'
          >
            <Link to='/teams/create'>チームを作成</Link>
          </Button>
        </div>
      )}
    </>
  );
};
