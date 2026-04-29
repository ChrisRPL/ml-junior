import {
  fetchFlowCatalog,
  fetchFlowPreview,
  type FlowCatalogItem,
  type FlowPreviewFetch,
  type FlowPreviewResponse,
} from './flow-preview-api';

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const catalogItem: FlowCatalogItem = {
  id: 'fine-tune-model',
  name: 'Fine-Tune Model',
  version: 'v1',
  description: 'Fine-tune with inspection, training, evaluation, and packaging.',
  metadata: {
    category: 'training',
    runtime_class: 'training',
    tags: ['fine-tuning', 'datasets'],
  },
  template_source: {
    kind: 'builtin',
    path: 'backend/builtin_flow_templates/fine-tune-model.json',
    schema_version: 'v1',
    template_version: 'v1',
  },
  phase_count: 3,
  required_inputs: ['base_model', 'dataset'],
  approval_point_count: 1,
  verifier_count: 2,
};

const preview: FlowPreviewResponse = {
  ...catalogItem,
  inputs: [
    {
      id: 'base_model',
      type: 'string',
      required: true,
      default: null,
      description: 'Base model identifier.',
    },
  ],
  required_inputs: [
    {
      id: 'base_model',
      type: 'string',
      required: true,
      default: null,
      description: 'Base model identifier.',
    },
  ],
  budgets: {
    max_gpu_hours: 6,
    max_runs: 5,
    max_wall_clock_hours: 18,
    max_llm_usd: 15,
  },
  phases: [
    {
      id: 'training',
      name: 'Training',
      objective: 'Run fine-tuning within budget.',
      status: 'pending',
      order: 1,
      required_outputs: ['training-metrics'],
      approval_points: ['launch-training'],
      verifiers: ['metric-recorded'],
    },
  ],
  approval_points: [
    {
      id: 'launch-training',
      risk: 'medium',
      action: 'launch',
      target: 'fine-tuning-job',
      description: 'Start the budgeted run.',
      phase_ids: ['training'],
    },
  ],
  required_outputs: [
    {
      id: 'training-metrics',
      type: 'metrics',
      description: 'Training and validation metrics.',
      required: true,
      phase_ids: ['training'],
    },
  ],
  artifacts: [
    {
      id: 'adapter-or-checkpoint',
      type: 'model',
      description: 'Fine-tuned adapter or checkpoint.',
      required: true,
    },
  ],
  verifier_checks: [
    {
      id: 'metric-recorded',
      type: 'metric',
      description: 'Metrics include split, step, and run identifier.',
      required: true,
      phase_ids: ['training'],
    },
  ],
  risky_operations: [
    {
      id: 'launch-training',
      risk: 'medium',
      action: 'launch',
      target: 'fine-tuning-job',
      description: 'Start the budgeted run.',
      source: 'approval_point',
      phase_ids: ['training'],
    },
  ],
};

async function testCatalogHappyPath(): Promise<void> {
  let path = '';
  const fetcher: FlowPreviewFetch = async (nextPath) => {
    path = nextPath;
    return response(200, [catalogItem]);
  };

  const result = await fetchFlowCatalog(fetcher);
  assert(path === '/api/flows', 'should fetch flow catalog path');
  assert(result.ok, 'catalog should load');
  assert(result.ok && result.catalog[0]?.required_inputs[0] === 'base_model', 'catalog should preserve required inputs');
}

async function testPreviewHappyPath(): Promise<void> {
  let path = '';
  const fetcher: FlowPreviewFetch = async (nextPath) => {
    path = nextPath;
    return response(200, preview);
  };

  const result = await fetchFlowPreview('fine-tune-model', fetcher);
  assert(path === '/api/flows/fine-tune-model/preview', 'should fetch flow preview path');
  assert(result.ok, 'preview should load');
  assert(result.ok && result.preview.phases[0]?.approval_points[0] === 'launch-training', 'preview should preserve phase approval refs');
  assert(result.ok && result.preview.risky_operations.length === 1, 'preview should surface risky operations');
}

async function testMalformedCatalog(): Promise<void> {
  const fetcher: FlowPreviewFetch = async () => response(200, { id: 'not-a-list' });
  const result = await fetchFlowCatalog(fetcher);

  assert(!result.ok, 'malformed catalog should fail');
  assert(!result.ok && result.warning === 'flow_catalog_malformed', 'malformed catalog warning should be explicit');
}

async function testMissingBackend(): Promise<void> {
  const fetcher: FlowPreviewFetch = async () => {
    throw new Error('connect ECONNREFUSED');
  };
  const result = await fetchFlowPreview('fine tune/model', fetcher);

  assert(!result.ok, 'missing backend should fail');
  assert(!result.ok && result.warning === 'flow_preview_backend_unavailable', 'missing backend warning should be explicit');
}

async function run(): Promise<void> {
  await testCatalogHappyPath();
  await testPreviewHappyPath();
  await testMalformedCatalog();
  await testMissingBackend();
}

run().then(() => {
  console.log('flow-preview-api: 4 tests passed');
});
