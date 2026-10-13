import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type ChangeEvent,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload,
  Cpu,
  BookOpen,
  Scale,
  FileText,
  Check,
  ChevronLeft,
  Play,
  Printer,
  Download,
  Copy,
  Wrench,
  Search,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { PageHeader } from '@/components/common/PageHeader';
import { DemoBadge } from '@/components/common/DemoBadge';
import { LoadingState } from '@/components/common/LoadingState';
import { DisclaimerBanner } from '@/components/common/DisclaimerBanner';
import { VideoUploader } from '@/components/upload/VideoUploader';
import { VideoPreview } from '@/components/upload/VideoPreview';
import { VehicleList } from '@/components/tracking/VehicleList';
import { TrackingOverlay } from '@/components/tracking/TrackingOverlay';
import { Timeline } from '@/components/tracking/Timeline';
import { VLMDescription } from '@/components/analysis/VLMDescription';
import { LegalCitationCard } from '@/components/analysis/LegalCitationCard';
import { LiabilityReport } from '@/components/analysis/LiabilityReport';
import { EvidenceCard } from '@/components/analysis/EvidenceCard';
import { exportElementToPDF } from '@/utils/pdfExport';
import { ErrorState } from '@/components/common/ErrorState';
import { isMockMode } from '@/services/apiClient';
import { uploadVideo, startAnalysis } from '@/services/accidentService';
import { useAnalysisPipeline, isInProgress } from '@/hooks/useAnalysis';
import type { VehicleTrack, VLMAnalysis, LiabilityAssessment } from '@/types/accident';
import type { TrafficLaw } from '@/types/law';

// ── Step metadata ──────────────────────────────────────────────────────────

const STEPS = [
  { id: 1, label: 'Upload', icon: Upload },
  { id: 2, label: 'Tracking', icon: Cpu },
  { id: 3, label: 'VLM Analysis', icon: Cpu },
  { id: 4, label: 'Law Retrieval', icon: BookOpen },
  { id: 5, label: 'Liability', icon: Scale },
  { id: 6, label: 'Report', icon: FileText },
] as const;

type StepId = (typeof STEPS)[number]['id'];

// ── Step Progress Indicator ────────────────────────────────────────────────

interface StepIndicatorProps {
  current: StepId;
  maxReached: StepId;
  onNavigate: (step: StepId) => void;
}

function StepIndicator({ current, maxReached, onNavigate }: StepIndicatorProps) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1">
      {STEPS.map((step, idx) => {
        const done = step.id < current;
        const active = step.id === current;
        const reachable = step.id <= maxReached;

        return (
          <div key={step.id} className="flex items-center">
            <button
              onClick={() => reachable && onNavigate(step.id)}
              disabled={!reachable}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors
                ${active ? 'bg-primary text-white' : ''}
                ${done ? 'text-green-400 hover:bg-green-500/10 cursor-pointer' : ''}
                ${!done && !active ? 'text-slate-500 disabled:cursor-not-allowed' : ''}
              `}
              aria-current={active ? 'step' : undefined}
            >
              {done ? (
                <Check className="h-3 w-3 shrink-0" />
              ) : (
                <span className={`h-5 w-5 rounded-full flex items-center justify-center text-xs shrink-0 ${
                  active ? 'bg-white/20' : 'bg-[#1e2d45]'
                }`}>
                  {step.id}
                </span>
              )}
              <span className="hidden sm:inline">{step.label}</span>
            </button>
            {idx < STEPS.length - 1 && (
              <div className={`h-px w-4 ${step.id < current ? 'bg-green-500/40' : 'bg-[#1e2d45]'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

interface Metadata {
  location: string;
  incidentDate: string;
  description: string;
  notes: string;
}

export function NewAnalysisPage() {
  const navigate = useNavigate();
  const reportRef = useRef<HTMLDivElement>(null);

  const [step, setStep] = useState<StepId>(1);
  const [maxReached, setMaxReached] = useState<StepId>(1);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [metadata, setMetadata] = useState<Metadata>({
    location: '',
    incidentDate: '',
    description: '',
    notes: '',
  });

  // Step 2 — tracking state
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [videoDuration, setVideoDuration] = useState(0);
  const [selectedVehicleId, setSelectedVehicleId] = useState<string | null>(null);
  const [overlayEnabled, setOverlayEnabled] = useState(true);
  const [videoSize, setVideoSize] = useState({ width: 640, height: 360 });
  const [seekTo, setSeekTo] = useState<number | undefined>(undefined);

  // Step 4 — Law search
  const [lawQuery, setLawQuery] = useState('');
  const [activeTopics, setActiveTopics] = useState<string[]>([]);

  // ── Live pipeline state ────────────────────────────────────────────────
  const [accidentId, setAccidentId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // Polls the backend while the analysis pipeline runs
  const { accident, running, error: pipelineError, refetch } = useAnalysisPipeline(accidentId ?? undefined);

  const status = accident?.status;
  const stageLabel = accident?.stageLabel ?? '';
  const tracks: VehicleTrack[] = accident?.tracks ?? [];
  const vlmAnalysis: VLMAnalysis | null = accident?.vlmAnalysis ?? null;
  const laws: TrafficLaw[] = accident?.laws ?? [];
  const liability: LiabilityAssessment | null = accident?.liabilityAssessment ?? null;

  const vlmLoading = Boolean(accidentId) && !vlmAnalysis && isInProgress(status);
  const liabilityLoading = Boolean(accidentId) && !liability && isInProgress(status);
  const failed = status === 'failed';

  // ── Navigation ────────────────────────────────────────────────────────

  const goToStep = useCallback((s: StepId) => {
    setStep(s);
    setMaxReached((prev) => (s > prev ? s : prev));
  }, []);

  // Unlock steps as the backend produces each stage's results
  useEffect(() => {
    if (!accident) return;
    let reached: StepId = 2;
    if (tracks.length > 0) reached = 2;
    if (vlmAnalysis) reached = 3;
    if (laws.length > 0) reached = 4;
    if (liability) reached = 5;
    if (accident.status === 'completed') reached = 6;
    setMaxReached((prev) => (reached > prev ? reached : prev));
  }, [accident, tracks.length, vlmAnalysis, laws.length, liability]);

  /** Step 1 → upload the video and start the real pipeline. */
  async function handleStart() {
    if (!videoFile || starting) return;
    setStarting(true);
    setStartError(null);
    try {
      const record = await uploadVideo(videoFile, {
        location: metadata.location,
        incidentDate: metadata.incidentDate,
        description: metadata.description,
        notes: metadata.notes,
      });
      setAccidentId(record.id);
      goToStep(2);
    } catch (err: unknown) {
      setStartError(err instanceof Error ? err.message : 'Could not upload the video.');
    } finally {
      setStarting(false);
    }
  }

  /** Re-run the pipeline after a failure. */
  async function handleRetry() {
    if (!accidentId) return;
    try {
      await startAnalysis(accidentId);
      refetch();
    } catch (err: unknown) {
      setStartError(err instanceof Error ? err.message : 'Could not start the analysis.');
    }
  }

  function advance() {
    if (step < 6) goToStep((step + 1) as StepId);
  }
  function back() {
    if (step > 1) setStep((step - 1) as StepId);
  }

  // Sync video element duration
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const onLoaded = () => setVideoDuration(el.duration || 0);
    el.addEventListener('loadedmetadata', onLoaded);
    return () => el.removeEventListener('loadedmetadata', onLoaded);
  }, [videoFile]);

  // Measure video element size for overlay
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    const obs = new ResizeObserver(() => {
      setVideoSize({ width: el.offsetWidth, height: el.offsetHeight });
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [step]);

  // ── Law filtering ────────────────────────────────────────────────────

  const allTopics = Array.from(new Set(laws.flatMap((l) => l.topics)));

  const filteredLaws = laws.filter((l) => {
    const q = lawQuery.toLowerCase();
    const matchesQuery =
      !q ||
      l.title.toLowerCase().includes(q) ||
      l.excerpt.toLowerCase().includes(q) ||
      l.section.toLowerCase().includes(q);
    const matchesTopic =
      activeTopics.length === 0 ||
      activeTopics.some((t) => l.topics.includes(t));
    return matchesQuery && matchesTopic;
  });

  function toggleTopic(t: string) {
    setActiveTopics((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  }

  // ── PDF Export ────────────────────────────────────────────────────────

  async function handleDownloadPDF() {
    if (!reportRef.current) {
      alert('PDF export is in prototype state. Connect to backend for full PDF generation.');
      return;
    }
    await exportElementToPDF(reportRef.current, {
      filename: `accident-intel-${accident?.id ?? 'report'}.pdf`,
      onError: (msg) => alert(msg),
    });
  }

  async function handleCopySummary() {
    const summary = `Accident-Intel Report — ${accident?.id ?? 'N/A'}\n\n` +
      `Location: ${accident?.location ?? metadata.location ?? 'N/A'}\n` +
      `Date: ${accident?.incidentDate ?? metadata.incidentDate ?? 'N/A'}\n` +
      `Vehicles: ${accident?.vehicleCount ?? 0}\n\n` +
      `Assessment: ${liability?.overallAssessment ?? 'N/A'}\n\n` +
      `Summary: ${vlmAnalysis?.summary ?? 'N/A'}`;
    await navigator.clipboard.writeText(summary).catch(() => undefined);
  }

  // ── Render helpers ────────────────────────────────────────────────────

  function renderStep() {
    switch (step) {
      case 1:
        return <Step1 />;
      case 2:
        return <Step2 />;
      case 3:
        return <Step3 />;
      case 4:
        return <Step4 />;
      case 5:
        return <Step5 />;
      case 6:
        return <Step6 />;
    }
  }

  // ── Step 1 ───────────────────────────────────────────────────────────

  function Step1() {
    function handleMetadataChange(
      field: keyof Metadata,
      value: string,
    ) {
      setMetadata((prev) => ({ ...prev, [field]: value }));
    }

    return (
      <div className="space-y-6 max-w-2xl">
        <VideoUploader
          file={videoFile}
          onFileSelect={setVideoFile}
          onRemove={() => setVideoFile(null)}
        />

        {videoFile && <VideoPreview file={videoFile} />}

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Optional Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="location">Accident Location</Label>
              <Input
                id="location"
                placeholder="e.g. 5th Ave & W 42nd St, Manhattan, NY"
                value={metadata.location}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  handleMetadataChange('location', e.target.value)
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="incidentDate">Incident Date &amp; Time</Label>
              <Input
                id="incidentDate"
                type="datetime-local"
                value={metadata.incidentDate}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  handleMetadataChange('incidentDate', e.target.value)
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="description">Description</Label>
              <Textarea
                id="description"
                placeholder="Brief description of the accident…"
                rows={3}
                value={metadata.description}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                  handleMetadataChange('description', e.target.value)
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="notes">Investigation Notes</Label>
              <Textarea
                id="notes"
                placeholder="Additional context or notes for the investigator…"
                rows={2}
                value={metadata.notes}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                  handleMetadataChange('notes', e.target.value)
                }
              />
            </div>
          </CardContent>
        </Card>

        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          <strong>Important:</strong> The system analyzes visible footage only. Events not visible in the video cannot be verified.
        </div>

        {startError && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {startError}
          </div>
        )}

        <Button
          onClick={() => void handleStart()}
          disabled={!videoFile || starting}
          size="lg"
          className="w-full sm:w-auto"
        >
          <Play className="h-4 w-4" />
          {starting ? 'Uploading & starting…' : 'Start Analysis'}
        </Button>
      </div>
    );
  }

  // ── Step 2 ───────────────────────────────────────────────────────────

  function Step2() {
    if (failed) {
      return <ErrorState message={accident?.error ?? 'The analysis failed.'} onRetry={handleRetry} />;
    }
    if (tracks.length === 0) {
      return (
        <div className="py-16">
          <LoadingState message={stageLabel || 'Running vehicle detection and tracking…'} />
        </div>
      );
    }

    return (
      <div className="space-y-6">
        {/* Data source banner */}
        <div className="flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-300">
          {isMockMode && <DemoBadge />}
          <span>
            {isMockMode
              ? 'Demo Mode — Mock bounding boxes are displayed. No real object-detection is running.'
              : `YOLO11x + BoT-SORT tracked ${tracks.length} vehicle${tracks.length === 1 ? '' : 's'} in this clip.`}
          </span>
          {running && <span className="ml-auto text-xs text-slate-400">{stageLabel}…</span>}
        </div>

        {/* Split layout */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Left: Video + overlay */}
          <div className="space-y-2">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Original Video
              </p>
              <div className="flex items-center gap-2">
                <Label htmlFor="overlay-toggle" className="text-xs text-slate-400 cursor-pointer">
                  Tracking Overlay
                </Label>
                <Switch
                  id="overlay-toggle"
                  checked={overlayEnabled}
                  onCheckedChange={setOverlayEnabled}
                />
              </div>
            </div>

            <div className="relative rounded-xl overflow-hidden bg-black">
              {videoFile ? (
                <>
                  <VideoPreview
                    file={videoFile}
                    seekTo={seekTo}
                    onTimeUpdate={(t) => setCurrentTime(t)}
                    videoRef={videoRef}
                  />
                  <div className="absolute inset-0 pointer-events-none top-0 left-0"
                    style={{ aspectRatio: '16/9' }}>
                    <TrackingOverlay
                      tracks={tracks}
                      selectedId={selectedVehicleId}
                      currentTime={currentTime}
                      enabled={overlayEnabled}
                      width={videoSize.width}
                      height={videoSize.height}
                    />
                  </div>
                </>
              ) : (
                /* No local preview (e.g. reopened later) — overlay only */
                <div className="aspect-video flex items-center justify-center bg-[#0d1525] rounded-xl">
                  <div className="text-center">
                    {isMockMode && <DemoBadge className="mb-2" />}
                    <p className="text-sm text-slate-400">No local video preview — tracking overlay only</p>
                    <TrackingOverlay
                      tracks={tracks}
                      selectedId={selectedVehicleId}
                      currentTime={currentTime}
                      enabled={overlayEnabled}
                      width={640}
                      height={360}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Overlay notice */}
            <p className="text-xs text-slate-500 text-center">
              {isMockMode
                ? 'Demo Tracking Overlay — mock bounding boxes for illustration only'
                : 'Tracking Overlay — bounding boxes are the tracker’s output, drawn on your video'}
            </p>
          </div>

          {/* Right: Vehicle list */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Detected Vehicles
            </p>
            <VehicleList
              tracks={tracks}
              selectedId={selectedVehicleId}
              onSelect={(id) =>
                setSelectedVehicleId((prev) => (prev === id ? null : id))
              }
            />
          </div>
        </div>

        {/* Timeline */}
        <Timeline
          tracks={tracks}
          duration={videoDuration || 15}
          currentTime={currentTime}
          onSeek={(t) => setSeekTo(t)}
        />

        <StepNav onBack={back} onContinue={advance} continueLabel="Continue to VLM Analysis" />
      </div>
    );
  }

  // ── Step 3 ───────────────────────────────────────────────────────────

  function Step3() {
    return (
      <div className="space-y-4 max-w-3xl">
        <div className="flex items-center gap-2 rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-300">
          {isMockMode && <DemoBadge />}
          <span>
            {isMockMode
              ? 'These observations are generated from mock data in this prototype.'
              : 'Observations produced by the vision-language model from your footage.'}
          </span>
        </div>

        <VLMDescription
          description={vlmAnalysis}
          loading={vlmLoading}
          onSeek={(t) => setSeekTo(t)}
        />

        {vlmAnalysis && (
          <StepNav onBack={back} onContinue={advance} continueLabel="Continue to Law Retrieval" />
        )}
      </div>
    );
  }

  // ── Step 4 ───────────────────────────────────────────────────────────

  function Step4() {
    return (
      <div className="space-y-4 max-w-3xl">
        {isMockMode ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            <strong>SAMPLE DATA:</strong> Law passages shown are demo excerpts for UI demonstration only. Do not use as legal reference.
          </div>
        ) : (
          <div className="rounded-lg border border-slate-500/30 bg-slate-500/10 px-4 py-3 text-sm text-slate-300">
            Law passages retrieved from the New York Vehicle &amp; Traffic Law index for this incident.
            Citations must still be verified by a qualified reviewer.
          </div>
        )}

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500 pointer-events-none" />
          <Input
            placeholder="Search laws by title, section, or content…"
            className="pl-9"
            value={lawQuery}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setLawQuery(e.target.value)}
          />
          {lawQuery && (
            <button
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              onClick={() => setLawQuery('')}
              aria-label="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Topic filter chips */}
        <div className="flex flex-wrap gap-2">
          {allTopics.map((topic) => (
            <button
              key={topic}
              onClick={() => toggleTopic(topic)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                activeTopics.includes(topic)
                  ? 'bg-primary text-white'
                  : 'bg-[#1e2d45] text-slate-400 hover:bg-[#253348]'
              }`}
            >
              {topic}
            </button>
          ))}
        </div>

        <p className="text-xs text-slate-500">
          {filteredLaws.length} of {laws.length} laws shown
        </p>

        <div className="space-y-4">
          {filteredLaws.map((law) => (
            <LegalCitationCard key={law.id} law={law} />
          ))}
          {filteredLaws.length === 0 && (
            <div className="text-center py-12 text-slate-500 text-sm">
              No laws match the current filter.
            </div>
          )}
        </div>

        <StepNav onBack={back} onContinue={advance} continueLabel="Continue to Liability Analysis" />
      </div>
    );
  }

  // ── Step 5 ───────────────────────────────────────────────────────────

  function Step5() {
    return (
      <div className="space-y-4 max-w-3xl">
        <LiabilityReport
          report={liability}
          loading={liabilityLoading}
          onSeek={(t) => setSeekTo(t)}
        />

        {liability && (
          <div className="space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              All Evidence
            </p>
            <div className="grid sm:grid-cols-2 gap-3">
              {liability.vehicleAnalyses.flatMap((va) =>
                va.evidence.map((ev) => (
                  <EvidenceCard key={ev.id} evidence={ev} onSeek={(t) => setSeekTo(t)} />
                )),
              )}
            </div>
            <StepNav onBack={back} onContinue={advance} continueLabel="Continue to Final Report" />
          </div>
        )}
      </div>
    );
  }

  // ── Step 6 ───────────────────────────────────────────────────────────

  function Step6() {
    return (
      <div className="space-y-6 max-w-4xl">
        {/* Action buttons */}
        <div className="flex flex-wrap gap-2">
          <Button onClick={handleDownloadPDF} variant="default" size="sm">
            <Download className="h-4 w-4" /> Download PDF
          </Button>
          <Button onClick={() => window.print()} variant="outline" size="sm">
            <Printer className="h-4 w-4" /> Print
          </Button>
          <Button onClick={handleCopySummary} variant="outline" size="sm">
            <Copy className="h-4 w-4" /> Copy Summary
          </Button>
          <Button onClick={() => setStep(1)} variant="ghost" size="sm">
            <ChevronLeft className="h-4 w-4" /> Return to Analysis
          </Button>
          <Button onClick={() => navigate('/damage')} variant="secondary" size="sm">
            <Wrench className="h-4 w-4" /> Estimate Repair Costs
          </Button>
        </div>

        {/* Report body */}
        <div ref={reportRef} className="space-y-6">
          {/* Demo banner */}
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            <DemoBadge />
            <span>This report is generated from mock/demo data for prototype purposes only.</span>
          </div>

          <DisclaimerBanner />

          {/* Accident Metadata */}
          <Card>
            <CardHeader>
              <CardTitle>Accident Metadata</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid sm:grid-cols-2 gap-x-8 gap-y-2 text-sm">
                <div>
                  <dt className="text-slate-400">Accident ID</dt>
                  <dd className="text-slate-100 font-mono">{accident?.id ?? 'N/A'}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">Video File</dt>
                  <dd className="text-slate-100 truncate">{videoFile?.name ?? accident?.videoFilename ?? 'N/A'}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">Location</dt>
                  <dd className="text-slate-100">{metadata.location || accident?.location || 'N/A'}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">Incident Date</dt>
                  <dd className="text-slate-100">{metadata.incidentDate || accident?.incidentDate || 'N/A'}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">Vehicles Detected</dt>
                  <dd className="text-slate-100">{accident?.vehicleCount ?? 0}</dd>
                </div>
                <div>
                  <dt className="text-slate-400">Liability Status</dt>
                  <dd>
                    <Badge variant="warning" className="text-xs">{accident?.liabilityStatus ?? 'pending'}</Badge>
                  </dd>
                </div>
              </dl>
              {(metadata.description || accident?.description) && (
                <div className="mt-4">
                  <dt className="text-slate-400 text-sm">Description</dt>
                  <dd className="text-slate-100 text-sm mt-1">
                    {metadata.description || accident?.description}
                  </dd>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Video preview */}
          {videoFile && (
            <Card>
              <CardHeader>
                <CardTitle>Video Preview</CardTitle>
              </CardHeader>
              <CardContent>
                <VideoPreview file={videoFile} />
              </CardContent>
            </Card>
          )}

          {/* Vehicle Tracking Summary */}
          {tracks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Vehicle Tracking Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid sm:grid-cols-2 gap-4">
                  {tracks.map((t) => (
                    <div key={t.id} className="rounded-lg border border-[#1e2d45] bg-[#0d1525] p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className="h-3 w-3 rounded-full shrink-0"
                          style={{ backgroundColor: t.color }}
                        />
                        <span className="font-semibold text-sm text-slate-100">{t.label}</span>
                        <Badge variant="secondary" className="ml-auto text-xs">{t.class}</Badge>
                      </div>
                      <p className="text-xs text-slate-400">
                        First seen: {t.firstSeen.toFixed(1)}s · Last seen: {t.lastSeen.toFixed(1)}s
                      </p>
                      {t.speed !== undefined && (
                        <p className="text-xs text-slate-400">Est. speed: {t.speed} km/h</p>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Accident Timeline */}
          {vlmAnalysis && (
            <Card>
              <CardHeader>
                <CardTitle>Accident Timeline</CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="space-y-3">
                  {vlmAnalysis.timeline.map((ev, i) => (
                    <li key={i} className="flex gap-3 text-sm">
                      {ev.timestamp !== undefined && (
                        <span className="font-mono text-xs text-primary shrink-0 w-12">
                          {ev.timestamp.toFixed(1)}s
                        </span>
                      )}
                      <span
                        className={ev.type === 'fact' ? 'text-slate-200' : 'text-amber-200'}
                      >
                        {ev.content}
                      </span>
                      <Badge
                        variant={ev.type === 'fact' ? 'default' : 'warning'}
                        className="ml-auto text-xs shrink-0"
                      >
                        {ev.type}
                      </Badge>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          )}

          {/* VLM Description Summary */}
          {vlmAnalysis && (
            <Card>
              <CardHeader>
                <CardTitle>VLM Description Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-slate-300 mb-3">{vlmAnalysis.summary}</p>
                <p className="text-sm text-slate-300">{vlmAnalysis.collisionDescription}</p>
              </CardContent>
            </Card>
          )}

          {/* Retrieved Laws Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Retrieved Traffic Laws</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {laws.map((law) => (
                  <div key={law.id} className="rounded-lg border border-[#1e2d45] bg-[#0d1525] p-4">
                    <div className="flex items-start gap-2">
                      <span className="font-mono text-xs text-slate-500 shrink-0">{law.section}</span>
                      <span className="text-sm font-medium text-slate-100">{law.title}</span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1 italic">"{law.excerpt}"</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Liability Assessment */}
          {liability && (
            <LiabilityReport
              report={liability}
              loading={false}
              onSeek={(t) => setSeekTo(t)}
            />
          )}

          {/* Uncertainties */}
          {vlmAnalysis && vlmAnalysis.uncertainties.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Uncertainties &amp; Limitations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {vlmAnalysis.uncertainties.map((u, i) => (
                    <li key={i} className="text-sm text-amber-300 flex gap-2">
                      <span className="shrink-0">•</span>
                      {u}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <DisclaimerBanner />
        </div>

        <Button variant="ghost" size="sm" onClick={back}>
          <ChevronLeft className="h-4 w-4" /> Back to Liability Analysis
        </Button>
      </div>
    );
  }

  // ── Full page render ─────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <PageHeader
        title="New Accident Analysis"
        description="Upload footage and run an AI-powered investigation"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'New Analysis' },
        ]}
        actions={isMockMode ? <DemoBadge /> : undefined}
      />

      {/* Pipeline failure / connectivity notice */}
      {failed && step !== 2 && (
        <div className="flex items-center gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <span>
            {accident?.error ? `Analysis failed: ${accident.error}` : 'The analysis failed.'}
          </span>
          <Button variant="outline" size="sm" className="ml-auto" onClick={() => void handleRetry()}>
            Retry
          </Button>
        </div>
      )}
      {pipelineError && !failed && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
          {pipelineError}
        </div>
      )}

      {/* Step indicator */}
      <StepIndicator current={step} maxReached={maxReached} onNavigate={goToStep} />

      <div className="pt-2">{renderStep()}</div>
    </div>
  );
}

// ── Shared nav bar ─────────────────────────────────────────────────────────

interface StepNavProps {
  onBack: () => void;
  onContinue: () => void;
  continueLabel: string;
}

function StepNav({ onBack, onContinue, continueLabel }: StepNavProps) {
  return (
    <div className="flex items-center justify-between pt-2">
      <Button variant="outline" size="sm" onClick={onBack}>
        <ChevronLeft className="h-4 w-4" /> Back
      </Button>
      <Button size="sm" onClick={onContinue}>
        {continueLabel}
      </Button>
    </div>
  );
}
