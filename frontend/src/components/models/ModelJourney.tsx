import type { ModelDevStatus } from '../../types/platform';

/**
 * Visualizes a model version's development journey:
 * Initiated → Dev complete → Submitted to MRM → MRM review completed.
 *
 * Three renderings share the same step model:
 *  - ModelJourneyTrack: full-width labeled stepper for Model Registry rows
 *  - ModelJourneyMini: compact dot-stepper for narrow table cells
 *  - ModelJourney: full stepper with captions for the review detail page
 */

export const JOURNEY_LABELS = [
  'Initiated',
  'Dev complete',
  'Submitted to MRM',
  'MRM review completed',
] as const;

export const DEV_STATUS_META: Record<
  ModelDevStatus,
  { label: string; step: number; tone: 'progress' | 'approved' | 'rejected' }
> = {
  initiated: { label: 'Initiated', step: 0, tone: 'progress' },
  dev_complete: { label: 'Dev complete', step: 1, tone: 'progress' },
  submitted_to_mrm: { label: 'Submitted to MRM', step: 2, tone: 'progress' },
  mrm_approved: { label: 'MRM approved', step: 3, tone: 'approved' },
  mrm_rejected: { label: 'MRM rejected', step: 3, tone: 'rejected' },
};

export function ModelJourneyMini({ devStatus }: { devStatus?: ModelDevStatus }) {
  const meta = DEV_STATUS_META[devStatus ?? 'initiated'];
  const labelColor =
    meta.tone === 'approved'
      ? 'text-emerald-600'
      : meta.tone === 'rejected'
        ? 'text-red-600'
        : 'text-text-secondary';

  return (
    <div
      className="flex items-center gap-2.5"
      title={JOURNEY_LABELS.map((l, i) => `${i <= meta.step ? '●' : '○'} ${l}`).join('  ')}
    >
      <div className="flex items-center">
        {JOURNEY_LABELS.map((label, i) => {
          const reached = i <= meta.step;
          const terminal = i === 3;
          const dotColor = !reached
            ? 'bg-bg-elevated'
            : terminal && meta.tone === 'approved'
              ? 'bg-emerald-500'
              : terminal && meta.tone === 'rejected'
                ? 'bg-red-500'
                : 'bg-brand-purple';
          return (
            <div key={label} className="flex items-center">
              {i > 0 && (
                <span className={`h-px w-3 ${i <= meta.step ? 'bg-brand-purple/60' : 'bg-bg-elevated'}`} />
              )}
              <span className={`h-2 w-2 rounded-full ${dotColor}`} />
            </div>
          );
        })}
      </div>
      <span className={`whitespace-nowrap text-xs font-medium ${labelColor}`}>{meta.label}</span>
    </div>
  );
}

// ── Row track ────────────────────────────────────────────────────────────────
type TickState = 'done' | 'todo' | 'action' | 'approved' | 'rejected' | 'rework';

const TICK_CLASSES: Record<TickState, string> = {
  done: 'bg-brand-purple text-white shadow-sm',
  todo: 'border-2 border-bg-elevated bg-bg-card text-text-muted',
  action: 'border-2 border-brand-purple bg-bg-card text-brand-purple shadow-sm',
  approved: 'bg-emerald-500 text-white shadow-sm',
  rejected: 'bg-red-500 text-white shadow-sm',
  // Rejected models come BACK to dev: the dev milestone reopens in amber.
  rework: 'border-2 border-amber-500 bg-bg-card text-amber-600 shadow-sm',
};

/** A milestone circle on the track. When `onClick` is set, clicking it
 * advances the journey to the next stage (attach results / submit to MRM). */
function Tick({
  state,
  busy = false,
  onClick,
  title,
}: {
  state: TickState;
  busy?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const cls = `relative z-10 flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded-full transition ${
    busy ? 'border-2 border-brand-purple bg-bg-card text-brand-purple' : TICK_CLASSES[state]
  }`;
  const icon = busy ? (
    <span className="h-2.5 w-2.5 animate-spin-slow rounded-full border-2 border-current/30 border-t-current" />
  ) : state === 'rejected' ? (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5">
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  ) : state === 'done' || state === 'approved' ? (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5">
      <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : state === 'action' ? (
    // Chevron: "advance to the next stage"
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : state === 'rework' ? (
    // Redo arrow: the phase reopened after an MRM rejection
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ) : (
    <span className="h-1.5 w-1.5 rounded-full bg-bg-elevated" />
  );

  if (onClick && !busy) {
    const ring =
      state === 'rework'
        ? 'hover:ring-amber-500/25 focus-visible:ring-amber-500/35'
        : 'hover:ring-brand-purple/20 focus-visible:ring-brand-purple/30';
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        aria-label={title}
        className={`${cls} cursor-pointer hover:scale-110 hover:ring-4 focus-visible:ring-4 ${ring}`}
      >
        {icon}
      </button>
    );
  }
  return (
    <span className={cls} title={title}>
      {icon}
    </span>
  );
}

/** One phase of the track: a stretch of the baseline with its legend floating
 * centered above the line. */
function TrackSegment({
  legend,
  filled,
  small = false,
  tone = 'muted',
}: {
  legend?: import('react').ReactNode;
  /** Whether this stretch of the baseline is filled (phase completed). */
  filled: boolean;
  small?: boolean;
  tone?: 'muted' | 'done' | 'action' | 'approved' | 'rejected' | 'rework';
}) {
  const toneClass = {
    muted: 'text-text-muted',
    done: 'text-text-primary',
    action: 'font-semibold text-brand-purple',
    approved: 'font-semibold text-emerald-600',
    rejected: 'font-semibold text-red-600',
    rework: 'font-semibold text-amber-600',
  }[tone];
  const lineClass = !filled
    ? 'bg-bg-elevated'
    : tone === 'rework'
      ? 'bg-amber-400'
      : tone === 'rejected'
        ? 'bg-red-300'
        : 'bg-brand-purple';
  return (
    <div className={`relative self-stretch ${small ? 'w-14 flex-none' : 'min-w-[104px] flex-1'}`}>
      <span className={`absolute inset-x-0 bottom-[10px] h-0.5 ${lineClass}`} />
      {legend && (
        <span
          className={`absolute inset-x-0 bottom-[26px] flex items-end justify-center whitespace-nowrap text-[11px] font-medium leading-none ${toneClass}`}
        >
          {legend}
        </span>
      )}
    </div>
  );
}

/** Full-width journey track for a Model Registry table row.
 *
 * A continuous baseline that fills as the model advances, with milestone
 * circles between phases and each phase's legend floating above its stretch
 * of the line: init ✓ Dev complete ✓ Submitted to MRM ✓ MRM decision ✓ stage.
 *
 * The circles are the controls: when the callbacks are provided and the
 * journey allows it, the next milestone renders as a chevron circle —
 * clicking it advances the journey (open attach-results, submit to MRM). */
export function ModelJourneyTrack({
  devStatus,
  onAttachResults,
  onSubmitToMrm,
  submitting = false,
  stage,
  onAdvanceStage,
}: {
  devStatus?: ModelDevStatus;
  /** Opens the attach-results dialog. Active until a review is pending or
   * approved (the version is locked server-side after that). */
  onAttachResults?: () => void;
  /** Submits the version for MRM review. Active once results are attached,
   * and again after a rejection (resubmit). */
  onSubmitToMrm?: () => void;
  /** True while the submit-for-review call is in flight. */
  submitting?: boolean;
  /** Governance stage shown as the trailing legend
   * (None/Staging/Production/Archived). */
  stage?: string;
  /** Promotes to the next stage (None → Staging → Production). When set, the
   * terminal circle renders as a clickable chevron. */
  onAdvanceStage?: () => void;
}) {
  const status = devStatus ?? 'initiated';
  const meta = DEV_STATUS_META[status];
  const attachable = !!onAttachResults && ['initiated', 'dev_complete', 'mrm_rejected'].includes(status);
  const submittable = !!onSubmitToMrm && !submitting && ['dev_complete', 'mrm_rejected'].includes(status);

  const devDone = meta.step >= 1;
  const submitted = meta.step >= 2;
  const decided = meta.step >= 3;
  const approved = meta.tone === 'approved';
  const rejected = meta.tone === 'rejected';

  return (
    <div className="flex h-12 w-full min-w-[620px] items-end pb-0.5">
      {/* init: registered — always done for anything listed here */}
      <TrackSegment legend="Init" small filled tone="muted" />
      <Tick state="done" title="Registered" />

      {/* dev phase — click the circle to attach/edit results until submission
          locks it. A rejection sends the journey BACK here: the phase reopens
          in amber as "Dev Rework". */}
      <TrackSegment
        legend={rejected ? 'Dev Rework' : devDone ? 'Dev complete' : 'Dev Progress'}
        filled={devDone}
        tone={rejected ? 'rework' : devDone ? 'done' : attachable ? 'action' : 'muted'}
      />
      <Tick
        state={rejected ? 'rework' : devDone ? 'done' : attachable ? 'action' : 'todo'}
        onClick={attachable ? onAttachResults : undefined}
        title={
          rejected
            ? attachable
              ? 'Rejected by MRM — rework the model and update the attached results'
              : 'Rejected by MRM — rework required'
            : attachable
              ? devDone
                ? 'Edit the attached results (locked once submitted)'
                : 'Attach the trained artifact and results'
              : devDone
                ? 'Results attached'
                : undefined
        }
      />

      {/* submission phase — click the circle to submit (or resubmit after
          rejection; the stretch resets since the journey went back to dev) */}
      <TrackSegment
        legend={rejected ? 'Resubmit to MRM' : submitted ? 'Submitted to MRM' : 'Submit to MRM'}
        filled={submitted && !rejected}
        tone={submittable ? 'action' : submitted && !rejected ? 'done' : 'muted'}
      />
      <Tick
        state={submitted && !submittable ? 'done' : submittable ? 'action' : 'todo'}
        busy={submitting}
        onClick={submittable ? onSubmitToMrm : undefined}
        title={
          submittable
            ? rejected
              ? 'Resubmit for MRM review'
              : 'Submit for MRM review'
            : submitted
              ? 'Awaiting MRM'
              : 'Attach results first'
        }
      />

      {/* MRM decision */}
      <TrackSegment
        legend={decided ? meta.label : 'MRM review'}
        filled={decided}
        tone={approved ? 'approved' : rejected ? 'rejected' : decided ? 'done' : 'muted'}
      />
      <Tick
        state={approved ? 'approved' : rejected ? 'rejected' : 'todo'}
        title={approved ? 'Approved by MRM' : rejected ? 'Rejected by MRM' : 'Pending MRM decision'}
      />

      {/* Lifecycle stage rides the trailing stretch, closed by a terminal
          circle: Dev (in development) → Review (with MRM) → Prod ready
          (approved, awaiting promotion) → Approved for Prod (promoted).
          Once approved, the chevron prompts for a ServiceNow change ticket. */}
      {stage && (
        <>
          <TrackSegment
            legend={
              stage === 'Production'
                ? 'Approved for Prod'
                : stage === 'Archived'
                  ? 'Archived'
                  : approved
                    ? 'Prod ready'
                    : submitted
                      ? 'Review'
                      : 'Dev'
            }
            filled={stage === 'Production'}
            tone={
              stage === 'Production' || approved
                ? 'approved'
                : stage === 'Archived'
                  ? 'muted'
                  : rejected
                    ? 'rework'
                    : 'muted'
            }
          />
          <Tick
            state={stage === 'Production' ? 'approved' : onAdvanceStage ? 'action' : 'todo'}
            onClick={onAdvanceStage}
            title={
              stage === 'Production'
                ? 'Approved for Prod'
                : stage === 'Archived'
                  ? 'Archived'
                  : onAdvanceStage
                    ? 'Promote to Production — a ServiceNow change ticket will be requested'
                    : approved
                      ? 'Prod ready — awaiting promotion'
                      : submitted
                        ? 'In MRM review'
                        : 'In development'
            }
          />
        </>
      )}
    </div>
  );
}

// ── Full stepper ─────────────────────────────────────────────────────────────
export interface JourneyStep {
  label: string;
  /** Small line under the label — a date, a person, a hint. */
  caption?: string;
  state: 'done' | 'current' | 'todo' | 'approved' | 'rejected';
}

const STEP_CIRCLE: Record<JourneyStep['state'], string> = {
  done: 'border-brand-purple bg-brand-purple/15 text-brand-purple',
  current: 'border-brand-purple bg-brand-purple text-white',
  todo: 'border-bg-elevated bg-bg-dark text-text-muted',
  approved: 'border-emerald-500 bg-emerald-500/15 text-emerald-600',
  rejected: 'border-red-500 bg-red-500/15 text-red-600',
};

function StepIcon({ state, index }: { state: JourneyStep['state']; index: number }) {
  if (state === 'done' || state === 'approved') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
        <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (state === 'rejected') {
    return (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
        <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
      </svg>
    );
  }
  return <span className="text-xs font-semibold">{index + 1}</span>;
}

export function ModelJourney({ steps }: { steps: JourneyStep[] }) {
  return (
    <ol className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-0">
      {steps.map((step, i) => {
        const connectorDone = step.state !== 'todo';
        return (
          <li key={step.label} className="flex flex-1 items-start gap-3 sm:flex-col sm:items-center sm:gap-2">
            <div className="flex items-center sm:w-full">
              {/* Left connector (hidden for the first step) */}
              <span
                className={`hidden h-0.5 flex-1 sm:block ${
                  i === 0 ? 'bg-transparent' : connectorDone ? 'bg-brand-purple/50' : 'bg-bg-elevated'
                }`}
              />
              <span
                className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border-2 ${STEP_CIRCLE[step.state]} ${
                  step.state === 'current' ? 'shadow-[0_0_12px_rgba(108,99,197,0.5)]' : ''
                }`}
              >
                <StepIcon state={step.state} index={i} />
              </span>
              {/* Right connector (hidden for the last step) */}
              <span
                className={`hidden h-0.5 flex-1 sm:block ${
                  i === steps.length - 1
                    ? 'bg-transparent'
                    : steps[i + 1].state !== 'todo'
                      ? 'bg-brand-purple/50'
                      : 'bg-bg-elevated'
                }`}
              />
            </div>
            <div className="sm:px-2 sm:text-center">
              <p
                className={`text-sm font-medium ${
                  step.state === 'todo'
                    ? 'text-text-muted'
                    : step.state === 'approved'
                      ? 'text-emerald-600'
                      : step.state === 'rejected'
                        ? 'text-red-600'
                        : 'text-text-primary'
                }`}
              >
                {step.label}
              </p>
              {step.caption && <p className="mt-0.5 text-xs text-text-muted">{step.caption}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
