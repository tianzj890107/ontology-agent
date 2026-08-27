import test from "node:test";
import assert from "node:assert/strict";
import {
  approvalsNeedingAutoApprove,
  mergeEvents,
  unresolvedApprovalRequests,
} from "../src/eventSync.js";

function approvalRequest(id, seq, extra = {}) {
  return { type: "approval_request", id, seq, ...extra };
}

function approvalResult(id, seq, extra = {}) {
  return { type: "approval_result", id, seq, approved: true, ...extra };
}

test("unresolvedApprovalRequests：一个未决请求", () => {
  const pending = unresolvedApprovalRequests([approvalRequest("r1", 1)]);
  assert.equal(pending.length, 1);
  assert.equal(pending[0].id, "r1");
});

test("unresolvedApprovalRequests：已有结果的请求被排除", () => {
  const events = [approvalRequest("r1", 1), approvalResult("r1", 2)];
  assert.deepEqual(unresolvedApprovalRequests(events), []);
});

test("unresolvedApprovalRequests：多个请求部分已处理", () => {
  const events = [
    approvalRequest("r1", 1),
    approvalRequest("r2", 2),
    approvalRequest("r3", 3),
    approvalResult("r2", 4),
  ];
  const ids = unresolvedApprovalRequests(events).map((item) => item.id);
  assert.deepEqual(ids, ["r1", "r3"]);
});

test("unresolvedApprovalRequests：重复 ID 只返回一次", () => {
  const events = [approvalRequest("r1", 1), approvalRequest("r1", 2)];
  assert.equal(unresolvedApprovalRequests(events).length, 1);
});

test("unresolvedApprovalRequests：无 ID 的非法请求被忽略", () => {
  const events = [
    { type: "approval_request", seq: 1 },
    { type: "approval_request", id: "", seq: 2 },
    approvalRequest("r1", 3),
  ];
  assert.deepEqual(unresolvedApprovalRequests(events).map((item) => item.id), ["r1"]);
});

test("unresolvedApprovalRequests：按 seq 稳定排序", () => {
  const events = [approvalRequest("r2", 2), approvalRequest("r1", 1)];
  assert.deepEqual(unresolvedApprovalRequests(events).map((item) => item.id), ["r1", "r2"]);
});

test("unresolvedApprovalRequests：跨 run_started/done 边界仍正确识别", () => {
  const events = [
    approvalRequest("old", 1),
    { type: "run_started", seq: 2 },
    approvalResult("old", 3),
    { type: "done", seq: 4 },
    approvalRequest("new", 5),
  ];
  assert.deepEqual(unresolvedApprovalRequests(events).map((item) => item.id), ["new"]);
});

test("approvalsNeedingAutoApprove：轮询新请求触发自动确认", () => {
  const merged = mergeEvents([approvalRequest("r1", 1)], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [approvalRequest("r1", 1)],
    autoApprove: true,
    pendingApproval: null,
    inFlightIds: [],
  });
  assert.deepEqual(candidates, ["r1"]);
});

test("approvalsNeedingAutoApprove：下一次轮询不重复调用（非新窗口且服务端已无挂起）", () => {
  const merged = mergeEvents([approvalRequest("r1", 1)], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [],
    autoApprove: true,
    pendingApproval: null,
    inFlightIds: [],
  });
  assert.deepEqual(candidates, []);
});

test("approvalsNeedingAutoApprove：in-flight 中的 id 不重复提交", () => {
  const merged = mergeEvents([approvalRequest("r1", 1)], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [approvalRequest("r1", 1)],
    autoApprove: true,
    pendingApproval: null,
    inFlightIds: ["r1"],
  });
  assert.deepEqual(candidates, []);
});

test("approvalsNeedingAutoApprove：关闭时不自动批准", () => {
  const merged = mergeEvents([approvalRequest("r1", 1)], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [approvalRequest("r1", 1)],
    autoApprove: false,
    pendingApproval: { id: "r1", tool: "Bash", summary: "执行命令" },
    inFlightIds: [],
  });
  assert.deepEqual(candidates, []);
});

test("approvalsNeedingAutoApprove：刷新恢复时只批准服务端仍挂起的请求", () => {
  const merged = mergeEvents([
    approvalRequest("old-stale", 1),
    approvalRequest("live", 5),
  ], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [],
    autoApprove: true,
    pendingApproval: { id: "live", tool: "Bash", summary: "执行命令" },
    inFlightIds: [],
  });
  assert.deepEqual(candidates, ["live"]);
});

test("approvalsNeedingAutoApprove：历史过期请求且服务端 pendingApproval=null 不批准", () => {
  const merged = mergeEvents([approvalRequest("old-stale", 1)], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [],
    autoApprove: true,
    pendingApproval: null,
    inFlightIds: [],
  });
  assert.deepEqual(candidates, []);
});

test("approvalsNeedingAutoApprove：已处理请求即使服务端残留也不会重复批准", () => {
  const merged = mergeEvents([
    approvalRequest("r1", 1),
    approvalResult("r1", 2),
  ], [], "task:t");
  const candidates = approvalsNeedingAutoApprove({
    events: merged,
    freshEvents: [approvalRequest("r1", 1)],
    autoApprove: true,
    pendingApproval: { id: "r1", tool: "Bash", summary: "执行命令" },
    inFlightIds: [],
  });
  assert.deepEqual(candidates, []);
});
