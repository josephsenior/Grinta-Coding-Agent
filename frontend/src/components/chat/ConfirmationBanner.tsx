import { useState } from "react";
import { ShieldAlert, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SecurityRiskBadge } from "./EventCards";
import { sendUserAction } from "@/socket/client";
import type { ForgeEvent, ActionEvent } from "@/types/events";
import { ActionSecurityRisk } from "@/types/agent";

interface ConfirmationBannerProps {
  /** The most recent events — used to resolve pending action if pendingAction is not supplied */
  events?: ForgeEvent[];
  /** Optional explicit pending action to render confirmation for inline usage. */
  pendingAction?: ActionEvent;
  /** Visual treatment. "inline" anchors confirmation in the chat stream. */
  variant?: "default" | "inline";
}

export function ConfirmationBanner({ events = [], pendingAction, variant = "default" }: ConfirmationBannerProps) {
  const [rejectReason, setRejectReason] = useState("");
  const [showReasonInput, setShowReasonInput] = useState(false);

  // Find the last action event that has awaiting_confirmation status
  const resolvedPendingAction = pendingAction ?? [...events].reverse().find(
    (e) => "action" in e && (e as ActionEvent).confirmation_status === "awaiting_confirmation",
  ) as ActionEvent | undefined;

  const description = resolvedPendingAction
    ? resolvedPendingAction.message || `${resolvedPendingAction.action}: ${JSON.stringify(resolvedPendingAction.args)}`
    : "An action requires your approval";

  const risk = resolvedPendingAction?.security_risk as ActionSecurityRisk | undefined;
  const containerClassName =
    variant === "inline"
      ? "rounded-2xl bg-orange-500/[0.06] p-3.5 ring-1 ring-orange-500/15 dark:bg-orange-500/[0.08]"
      : "border-t border-border/40 bg-muted/15 p-3 sm:p-4";
  const contentClassName = variant === "inline" ? "space-y-3" : "mx-auto max-w-3xl space-y-3";

  const handleApprove = () => {
    sendUserAction({
      action: "change_agent_state",
      args: { agent_state: "user_confirmed" },
    });
  };

  const handleReject = () => {
    if (showReasonInput) {
      sendUserAction({
        action: "change_agent_state",
        args: {
          agent_state: "user_rejected",
          reason: rejectReason || undefined,
        },
      });
      setRejectReason("");
      setShowReasonInput(false);
    } else {
      setShowReasonInput(true);
    }
  };

  const handleRejectCancel = () => {
    setShowReasonInput(false);
    setRejectReason("");
  };

  return (
    <div className={containerClassName}>
      <div className={contentClassName}>
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-orange-600/80 dark:text-orange-400/80" />
          <div className="min-w-0 flex-1 space-y-1">
            <p className="text-[13px] font-medium text-foreground/90">Approve to continue</p>
            <p className="text-[12px] leading-relaxed text-muted-foreground line-clamp-4">{description}</p>
          </div>
          <SecurityRiskBadge risk={risk} />
        </div>

        {showReasonInput ? (
          <div className="flex items-center gap-2">
            <Input
              placeholder="Optional rejection reason..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleReject();
                if (e.key === "Escape") handleRejectCancel();
              }}
              autoFocus
              className="text-sm"
            />
            <Button size="sm" variant="destructive" onClick={handleReject}>
              <X className="mr-1 h-3 w-3" /> Deny
            </Button>
            <Button size="sm" variant="ghost" onClick={handleRejectCancel}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={handleReject}>
              <X className="mr-1 h-3 w-3" /> Deny
            </Button>
            <Button size="sm" onClick={handleApprove}>
              <Check className="mr-1 h-3 w-3" /> Approve
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
