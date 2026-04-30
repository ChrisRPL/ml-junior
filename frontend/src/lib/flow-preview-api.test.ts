import {
  fetchFlowCatalog,
  fetchFlowSources,
  fetchFlowPreview,
  type FlowCatalogItem,
  type FlowPreviewFetch,
  type FlowPreviewResponse,
  type FlowTemplateSourceDescriptor,
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

const flowSources: FlowTemplateSourceDescriptor[] = [
  {
    kind: 'builtin',
    label: 'Built-in',
    availability: 'available',
    trust_status: 'trusted',
    loading_status: 'enabled',
    template_count: 17,
    read_only: true,
    supports_upload: false,
    supports_remote_fetch: false,
    source_path: 'backend/builtin_flow_templates',
    description: 'Bundled templates loaded from the backend package only.',
  },
  {
    kind: 'custom',
    label: 'Custom',
    availability: 'reserved',
    trust_status: 'untrusted',
    loading_status: 'disabled',
    template_count: 0,
    read_only: true,
    supports_upload: false,
    supports_remote_fetch: false,
    source_path: null,
    description: 'Reserved for user-provided templates; loading is disabled.',
  },
  {
    kind: 'community',
    label: 'Community',
    availability: 'reserved',
    trust_status: 'untrusted',
    loading_status: 'disabled',
    template_count: 0,
    read_only: true,
    supports_upload: false,
    supports_remote_fetch: false,
    source_path: null,
    description: 'Reserved for curated shared templates; remote fetch is disabled.',
  },
];

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

async function testFlowSourcesHappyPath(): Promise<void> {
  let path = '';
  const fetcher: FlowPreviewFetch = async (nextPath) => {
    path = nextPath;
    return response(200, flowSources);
  };

  const result = await fetchFlowSources(fetcher);
  assert(path === '/api/flow-sources', 'should fetch flow sources path');
  assert(result.ok, 'flow sources should load');
  assert(result.ok && result.sources.length === 3, 'flow sources should preserve every descriptor');
  assert(result.ok && result.sources[0]?.trust_status === 'trusted', 'builtin source should preserve trust status');
  assert(result.ok && result.sources[1]?.loading_status === 'disabled', 'custom source should preserve loading status');
  assert(result.ok && result.sources[2]?.source_path === null, 'community source should preserve null source path');
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

async function testMappedVerifierMetadata(): Promise<void> {
  const mappedPreview: FlowPreviewResponse = {
    ...preview,
    verifier_checks: [
      {
        ...preview.verifier_checks[0]!,
        mapping_status: 'mapped',
        catalog_check_id: 'metric-parsed-from-output',
        catalog_check_name: 'Metric parsed from output',
        catalog_check_category: 'evaluation',
        catalog_check_type: 'metric',
        catalog_evidence_ref_types: ['metric', 'experiment'],
      },
    ],
    verifier_catalog_coverage: {
      verifier_count: 1,
      mapped_count: 1,
      unmapped_count: 0,
      intentional_unmapped_verifier_ids: [],
      unknown_unmapped_verifier_ids: [],
    },
  };
  const fetcher: FlowPreviewFetch = async () => response(200, mappedPreview);
  const result = await fetchFlowPreview('fine-tune-model', fetcher);

  assert(result.ok, 'mapped verifier metadata should load');
  assert(
    result.ok && result.preview.verifier_checks[0]?.catalog_check_id === 'metric-parsed-from-output',
    'mapped verifier should preserve catalog id',
  );
  assert(
    result.ok && result.preview.verifier_catalog_coverage?.mapped_count === 1,
    'mapped verifier should preserve coverage summary',
  );
}

async function testIntentionalUnmappedVerifierMetadata(): Promise<void> {
  const intentionalPreview: FlowPreviewResponse = {
    ...preview,
    verifier_checks: [
      {
        ...preview.verifier_checks[0]!,
        id: 'goal-is-testable',
        mapping_status: 'intentional_unmapped',
        catalog_check_id: null,
        catalog_check_name: null,
        catalog_check_category: null,
        catalog_check_type: null,
        catalog_evidence_ref_types: [],
      },
    ],
    verifier_catalog_coverage: {
      verifier_count: 1,
      mapped_count: 0,
      unmapped_count: 1,
      intentional_unmapped_verifier_ids: ['goal-is-testable'],
      unknown_unmapped_verifier_ids: [],
    },
  };
  const fetcher: FlowPreviewFetch = async () => response(200, intentionalPreview);
  const result = await fetchFlowPreview('literature-overview', fetcher);

  assert(result.ok, 'intentional unmapped verifier metadata should load');
  assert(
    result.ok && result.preview.verifier_checks[0]?.mapping_status === 'intentional_unmapped',
    'intentional unmapped status should be preserved',
  );
  assert(
    result.ok && result.preview.verifier_catalog_coverage?.intentional_unmapped_verifier_ids[0] === 'goal-is-testable',
    'intentional unmapped coverage id should be preserved',
  );
}

async function testUnknownUnmappedVerifierMetadata(): Promise<void> {
  const unknownPreview: FlowPreviewResponse = {
    ...preview,
    verifier_checks: [
      {
        ...preview.verifier_checks[0]!,
        id: 'new-local-check',
        mapping_status: 'unknown_unmapped',
        catalog_check_id: null,
        catalog_check_name: null,
        catalog_check_category: null,
        catalog_check_type: null,
        catalog_evidence_ref_types: [],
      },
    ],
    verifier_catalog_coverage: {
      verifier_count: 1,
      mapped_count: 0,
      unmapped_count: 1,
      intentional_unmapped_verifier_ids: [],
      unknown_unmapped_verifier_ids: ['new-local-check'],
    },
  };
  const fetcher: FlowPreviewFetch = async () => response(200, unknownPreview);
  const result = await fetchFlowPreview('custom', fetcher);

  assert(result.ok, 'unknown unmapped verifier metadata should load');
  assert(
    result.ok && result.preview.verifier_checks[0]?.mapping_status === 'unknown_unmapped',
    'unknown unmapped status should be preserved',
  );
  assert(
    result.ok && result.preview.verifier_catalog_coverage?.unknown_unmapped_verifier_ids[0] === 'new-local-check',
    'unknown unmapped coverage id should be preserved',
  );
}

async function testMalformedCatalog(): Promise<void> {
  const fetcher: FlowPreviewFetch = async () => response(200, { id: 'not-a-list' });
  const result = await fetchFlowCatalog(fetcher);

  assert(!result.ok, 'malformed catalog should fail');
  assert(!result.ok && result.warning === 'flow_catalog_malformed', 'malformed catalog warning should be explicit');
}

async function testMalformedFlowSources(): Promise<void> {
  const malformedSources: unknown[] = [
    {
      ...flowSources[0]!,
      loading_status: 'pending',
    },
    ...flowSources.slice(1),
  ];
  const fetcher: FlowPreviewFetch = async () => response(200, malformedSources);
  const result = await fetchFlowSources(fetcher);

  assert(!result.ok, 'malformed flow sources should fail');
  assert(!result.ok && result.warning === 'flow_sources_malformed', 'malformed flow sources warning should be explicit');
}

async function testMalformedOptionalVerifierMetadata(): Promise<void> {
  const malformedPreview = {
    ...preview,
    verifier_checks: [
      {
        ...preview.verifier_checks[0]!,
        mapping_status: 'partially_mapped',
      },
    ],
  };
  const fetcher: FlowPreviewFetch = async () => response(200, malformedPreview);
  const result = await fetchFlowPreview('fine-tune-model', fetcher);

  assert(!result.ok, 'malformed optional verifier metadata should fail');
  assert(!result.ok && result.warning === 'flow_preview_malformed', 'malformed optional verifier metadata warning should be explicit');
}

async function testMalformedOptionalCoverageMetadata(): Promise<void> {
  const malformedPreview = {
    ...preview,
    verifier_catalog_coverage: {
      verifier_count: 1,
      mapped_count: '1',
      unmapped_count: 0,
      intentional_unmapped_verifier_ids: [],
      unknown_unmapped_verifier_ids: [],
    },
  };
  const fetcher: FlowPreviewFetch = async () => response(200, malformedPreview);
  const result = await fetchFlowPreview('fine-tune-model', fetcher);

  assert(!result.ok, 'malformed optional coverage metadata should fail');
  assert(!result.ok && result.warning === 'flow_preview_malformed', 'malformed optional coverage metadata warning should be explicit');
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
  await testFlowSourcesHappyPath();
  await testPreviewHappyPath();
  await testMappedVerifierMetadata();
  await testIntentionalUnmappedVerifierMetadata();
  await testUnknownUnmappedVerifierMetadata();
  await testMalformedCatalog();
  await testMalformedFlowSources();
  await testMalformedOptionalVerifierMetadata();
  await testMalformedOptionalCoverageMetadata();
  await testMissingBackend();
}

run().then(() => {
  console.log('flow-preview-api: 11 tests passed');
});
