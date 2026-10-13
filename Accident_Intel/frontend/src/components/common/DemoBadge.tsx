import { FlaskConical } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { isMockMode } from '@/services/apiClient';

interface DemoBadgeProps {
  className?: string;
}

/**
 * "Demo Data" pill.
 *
 * Renders only when the app runs against local mock data
 * (VITE_MOCK_MODE=true). With the real backend connected there is nothing to
 * disclaim, so the component disappears instead of needing a call-site edit —
 * this keeps every existing usage honest.
 */
export function DemoBadge({ className }: DemoBadgeProps) {
  if (!isMockMode) return null;

  return (
    <Badge
      variant="outline"
      className={cn(
        'border-amber-500/40 bg-amber-500/10 text-amber-400 text-xs',
        className,
      )}
    >
      <FlaskConical className="h-3 w-3" />
      Demo Data
    </Badge>
  );
}
