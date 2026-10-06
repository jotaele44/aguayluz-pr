import { authorizeWaterMutation } from "./aguaWaterMutationGuard";

describe("AguaYLuz protected water-disruption mutations", () => {
  it("rejects anonymous mutation requests", () => {
    expect(authorizeWaterMutation(
      { userId: null, role: null, authenticated: false },
      { mutation: "CREATE_DISRUPTION", idempotencyKey: "k1" }
    ).status).toBe(401);
  });

  it("requires idempotency keys for protected mutations", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "operator", authenticated: true },
      { mutation: "CREATE_DISRUPTION" }
    ).reason).toBe("IDEMPOTENCY_KEY_REQUIRED");
  });

  it("allows operators to create disruption records", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "operator", authenticated: true },
      { mutation: "CREATE_DISRUPTION", idempotencyKey: "k1" }
    ).allowed).toBeTrue();
  });

  it("denies viewers from operational mutations", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "viewer", authenticated: true },
      { mutation: "RESOLVE_DISRUPTION", idempotencyKey: "k1" }
    ).status).toBe(403);
  });

  it("requires admin authority to publish alerts", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "operator", authenticated: true },
      { mutation: "PUBLISH_ALERT", idempotencyKey: "k1" }
    ).reason).toBe("ADMIN_REQUIRED");
  });

  it("requires admin authority to retract alerts", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "operator", authenticated: true },
      { mutation: "RETRACT_ALERT", idempotencyKey: "k1" }
    ).reason).toBe("ADMIN_REQUIRED");
  });

  it("allows admin alert publication", () => {
    expect(authorizeWaterMutation(
      { userId: "admin", role: "admin", authenticated: true },
      { mutation: "PUBLISH_ALERT", idempotencyKey: "k1" }
    ).allowed).toBeTrue();
  });

  it("fails closed on non-owner mutation for non-admin actors", () => {
    expect(authorizeWaterMutation(
      { userId: "u1", role: "operator", authenticated: true },
      { mutation: "UPDATE_DISRUPTION", resourceOwnerUserId: "u2", idempotencyKey: "k1" }
    ).reason).toBe("OWNER_OR_ADMIN_REQUIRED");
  });

  it("permits admin override of ownership", () => {
    expect(authorizeWaterMutation(
      { userId: "admin", role: "admin", authenticated: true },
      { mutation: "UPDATE_DISRUPTION", resourceOwnerUserId: "u2", idempotencyKey: "k1" }
    ).allowed).toBeTrue();
  });
});
