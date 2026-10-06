export type WaterMutation =
  | "CREATE_DISRUPTION"
  | "UPDATE_DISRUPTION"
  | "ACKNOWLEDGE_DISRUPTION"
  | "RESOLVE_DISRUPTION"
  | "PUBLISH_ALERT"
  | "RETRACT_ALERT";

export interface MutationActor {
  userId: string | null;
  role: "viewer" | "operator" | "admin" | null;
  authenticated: boolean;
}

export interface MutationRequest {
  mutation: WaterMutation;
  resourceOwnerUserId?: string | null;
  idempotencyKey?: string | null;
}

export interface MutationDecision {
  allowed: boolean;
  status: 200 | 401 | 403 | 409;
  reason: string;
}

const operatorMutations = new Set<WaterMutation>([
  "CREATE_DISRUPTION",
  "UPDATE_DISRUPTION",
  "ACKNOWLEDGE_DISRUPTION",
  "RESOLVE_DISRUPTION",
]);
const adminMutations = new Set<WaterMutation>(["PUBLISH_ALERT", "RETRACT_ALERT"]);

export function authorizeWaterMutation(actor: MutationActor, request: MutationRequest): MutationDecision {
  if (!actor.authenticated || !actor.userId) return { allowed: false, status: 401, reason: "AUTH_REQUIRED" };
  if (!request.idempotencyKey) return { allowed: false, status: 409, reason: "IDEMPOTENCY_KEY_REQUIRED" };
  if (adminMutations.has(request.mutation) && actor.role !== "admin") {
    return { allowed: false, status: 403, reason: "ADMIN_REQUIRED" };
  }
  if (operatorMutations.has(request.mutation) && actor.role !== "operator" && actor.role !== "admin") {
    return { allowed: false, status: 403, reason: "OPERATOR_REQUIRED" };
  }
  if (request.resourceOwnerUserId && actor.role !== "admin" && request.resourceOwnerUserId !== actor.userId) {
    return { allowed: false, status: 403, reason: "OWNER_OR_ADMIN_REQUIRED" };
  }
  return { allowed: true, status: 200, reason: "AUTHORIZED" };
}
