import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  App as AntApp,
  Button,
  ConfigProvider,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Popover,
  Select,
  Slider,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message,
} from "antd";
import "./styles.css";

const MISSION = window.__MISSION__?.taskCode ? window.__MISSION__ : null;
const $json = (value) => JSON.stringify(value, null, 2);
const esc = (value) => String(value ?? "");

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options });
  } catch (error) {
    return { error: `网络连接失败: ${error?.message || "无法连接服务"}` };
  }
  let body;
  try {
    body = await response.json();
  } catch {
    body = { error: `接口返回异常(${response.status})` };
  }
  if (!response.ok && !body.error) body.error = body.msg || `请求失败(${response.status})`;
  if (response.status === 401) body.error = body.error || "未获取到外部本体平台登录态，请从本体平台进入";
  return body;
}

function missionIdentity(task = null) {
  const repositoryId = String(task?.repositoryId || MISSION?.repositoryId || "").trim();
  const taskCode = String(task?.taskCode || MISSION?.taskCode || "").trim();
  if (!repositoryId || !taskCode) return null;
  return { repositoryId, taskCode };
}

function missionQuery(extra = {}, task = null) {
  const identity = missionIdentity(task);
  if (!identity) return "";
  const query = new URLSearchParams({ ...identity, ...extra });
  return `&${query.toString()}`;
}

function missionSearch(extra = {}, task = null) {
  const query = missionQuery(extra, task);
  return query ? `?${query.slice(1)}` : "";
}

function relativeTime(timestamp) {
  const seconds = Math.max(0, Date.now() / 1000 - Number(timestamp || 0));
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function truncateTitle(value, max = 15) {
  const text = String(value || "");
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function SendArrowIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fill="#fff" d="m1 7 13-5-2 11-6.97-3.802L13 3 3.794 8.523 1 7Zm4 8v-4.734L8 12l-3 3Z" />
    </svg>
  );
}

function CurrentMissionIcon() {
  return (
    <svg className="current-mission-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 1-.5-.5.49.49 0 0 1 .277-.45.488.488 0 0 1 .223-.05h4.733a.492.492 0 0 1 .5.5.491.491 0 0 1-.5.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" />
    </svg>
  );
}

function UploadFileIcon() {
  return (
    <svg className="composer-upload-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="m4.646 4.646 2.955-2.954a.491.491 0 0 1 .396-.192H8a.48.48 0 0 1 .359.152l2.995 2.994.002.003a.495.495 0 0 1-.004.707.49.49 0 0 1-.512.12.49.49 0 0 1-.192-.121l-.002-.001-2.149-2.15v7.465a.49.49 0 0 1-.5.498h-.002a.49.49 0 0 1-.498-.5V3.21L5.354 5.354h-.002a.495.495 0 0 1-.706-.001l-.001-.001a.495.495 0 0 1 .002-.705ZM2.5 8.003v4.664c0 .277.07.486.208.625.14.139.348.208.625.208h9.334c.277 0 .486-.069.625-.208.139-.14.208-.348.208-.625v-4.67A.49.49 0 0 1 14 7.5l.002.001a.495.495 0 0 1 .498.5v4.667c0 .253-.045.488-.134.703a1.82 1.82 0 0 1-.403.593c-.179.18-.377.313-.593.403a1.82 1.82 0 0 1-.703.134H3.333c-.253 0-.487-.045-.703-.134a1.821 1.821 0 0 1-.593-.403 1.82 1.82 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V8.003a.49.49 0 0 1 .5-.5.49.49 0 0 1 .5.5Z" />
    </svg>
  );
}

function DownloadSelectedIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M8.002 11.167a.488.488 0 0 0 .397-.193l2.954-2.954a.495.495 0 0 0 .002-.705l-.002-.002a.495.495 0 0 0-.705-.001l-.002.001-2.143 2.144V2a.491.491 0 0 0-.498-.5h-.002a.49.49 0 0 0-.45.277.487.487 0 0 0-.05.22v7.466l-2.15-2.15v-.001a.49.49 0 0 0-.513-.12.489.489 0 0 0-.192.12l-.002.001a.495.495 0 0 0-.002.705l.002.002 2.994 2.994a.49.49 0 0 0 .36.153h.002ZM2.5 8.003v4.664c0 .278.07.486.208.625.14.138.348.208.625.208h9.334c.277 0 .486-.07.625-.208.139-.14.208-.347.208-.625v-4.67A.491.491 0 0 1 14 7.5l.002.001a.495.495 0 0 1 .498.5v4.667c0 .253-.045.488-.134.703-.09.217-.224.414-.403.593a1.821 1.821 0 0 1-.592.403 1.82 1.82 0 0 1-.704.134H3.333a1.82 1.82 0 0 1-.703-.134 1.822 1.822 0 0 1-.593-.403 1.822 1.822 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V8.003a.491.491 0 0 1 .5-.5.49.49 0 0 1 .45.277c.033.067.05.142.05.223Z" />
    </svg>
  );
}

function CollapseFilePanelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M13.335 3H2.666a.49.49 0 0 0-.5.5.49.49 0 0 0 .5.5h10.667a.492.492 0 0 0 .5-.498V3.5a.489.489 0 0 0-.277-.45.488.488 0 0 0-.22-.05Zm-2.404 7.09 2.667-1.666a.5.5 0 0 0 0-.848L10.93 5.91a.498.498 0 0 0-.618.07.482.482 0 0 0-.147.354v3.334a.499.499 0 0 0 .388.487c.134.03.26.01.377-.063ZM2.666 6H8a.49.49 0 0 1 .449.277c.034.067.05.142.05.223v.002a.489.489 0 0 1-.277.447A.49.49 0 0 1 8 7H2.666a.49.49 0 0 1-.5-.5.49.49 0 0 1 .5-.5Zm8.5 2v-.765 1.53V8Zm-8.5 1H8a.49.49 0 0 1 .449.277c.034.067.05.142.05.223v.002a.489.489 0 0 1-.277.447A.49.49 0 0 1 8 10H2.666a.49.49 0 0 1-.5-.5.49.49 0 0 1 .5-.5Zm10.67 3H2.665a.49.49 0 0 0-.5.5.489.489 0 0 0 .277.45c.068.033.142.05.223.05h10.667a.49.49 0 0 0 .45-.277.487.487 0 0 0 .05-.22V12.5a.49.49 0 0 0-.277-.45.489.489 0 0 0-.22-.05Z" />
    </svg>
  );
}

function RefreshFilePanelIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M12.078 4.328c.326.365.602.774.828 1.228a.495.495 0 0 0 .668.226h.002a.495.495 0 0 0 .226-.669v-.002a6.49 6.49 0 0 0-.981-1.453 6.499 6.499 0 0 0-1.373-1.155 6.444 6.444 0 0 0-1.611-.738 6.476 6.476 0 0 0-1.86-.265c-.667 0-1.305.095-1.913.284a6.341 6.341 0 0 0-1.537.72 6.484 6.484 0 0 0-1.38 1.184V2.667a.49.49 0 0 0-.5-.5.49.49 0 0 0-.5.5v2.632a.492.492 0 0 0 .19.43c.025.02.053.037.082.051l.005.003h.001c.035.017.07.03.109.038a.467.467 0 0 0 .154.012h2.219a.495.495 0 0 0 .5-.497v-.003a.495.495 0 0 0-.498-.5H3.52a5.406 5.406 0 0 1 1.546-1.486 5.34 5.34 0 0 1 1.28-.602A5.396 5.396 0 0 1 7.977 2.5c.55 0 1.077.076 1.581.227.472.14.923.348 1.355.621.441.28.83.606 1.165.98Zm-8.984 6.116c.226.454.502.863.828 1.228.335.374.724.7 1.165.98.432.273.883.48 1.355.621a5.478 5.478 0 0 0 1.581.227c.57 0 1.113-.082 1.631-.245.446-.14.872-.34 1.28-.602a5.476 5.476 0 0 0 1.546-1.486h-1.387a.49.49 0 0 1-.449-.277.488.488 0 0 1-.05-.223.491.491 0 0 1 .5-.5h2.219a.493.493 0 0 1 .263.05.491.491 0 0 1 .204.185.492.492 0 0 1 .073.305v2.629a.495.495 0 0 1-.5.497h-.002a.495.495 0 0 1-.498-.5v-1.02a6.415 6.415 0 0 1-1.38 1.182 6.33 6.33 0 0 1-1.537.72 6.39 6.39 0 0 1-1.913.285 6.47 6.47 0 0 1-1.86-.265 6.444 6.444 0 0 1-1.61-.738 6.5 6.5 0 0 1-1.374-1.155 6.49 6.49 0 0 1-.98-1.453.49.49 0 0 1 .048-.525.487.487 0 0 1 .177-.145.49.49 0 0 1 .526.048c.06.045.108.104.144.177Z" />
    </svg>
  );
}

function TaskEditIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="m9.822 8.776 4.225-3.974c.184-.173.325-.367.42-.58.097-.213.149-.446.156-.7a1.82 1.82 0 0 0-.112-.707 1.82 1.82 0 0 0-.385-.605l-.183-.195a1.82 1.82 0 0 0-.58-.42 1.824 1.824 0 0 0-.7-.156 1.82 1.82 0 0 0-.707.112c-.219.083-.42.211-.605.385L7.13 5.906a1.158 1.158 0 0 0-.342.606l-.4 1.876a.824.824 0 0 0 .007.402c.035.125.104.24.205.347.1.106.213.18.336.22.123.042.257.05.402.027l1.873-.307a1.163 1.163 0 0 0 .61-.301Zm4.554 4.286v-5a.491.491 0 0 0-.498-.5h-.002a.491.491 0 0 0-.5.498v5.002c0 .167-.042.292-.125.375-.083.084-.208.125-.375.125h-10c-.167 0-.292-.041-.375-.125-.084-.083-.125-.208-.125-.375v-10c0-.166.041-.291.125-.375.083-.083.208-.125.375-.125h5a.491.491 0 0 0 .5-.498v-.002a.491.491 0 0 0-.5-.5h-5c-.207 0-.4.037-.576.11a1.487 1.487 0 0 0-.485.33 1.487 1.487 0 0 0-.33.484c-.073.177-.11.37-.11.576v10c0 .207.037.4.11.576.074.177.184.339.33.485.146.146.308.256.485.33.177.073.369.11.576.11h10c.207 0 .399-.037.576-.11.176-.074.338-.184.484-.33.147-.146.257-.308.33-.485a1.49 1.49 0 0 0 .11-.576Zm-.823-9.252a.83.83 0 0 1-.191.264L9.137 8.047a.17.17 0 0 1-.087.043l-1.633.268.35-1.637a.167.167 0 0 1 .048-.087l4.221-3.97c.203-.19.402-.282.598-.276.197.006.39.11.58.312l.184.196a.828.828 0 0 1 .175.274c.037.1.054.207.05.322a.827.827 0 0 1-.07.318Z" />
    </svg>
  );
}

function TaskCompleteIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#fff" d="M14.698 3.933 6.46 12.132a1.16 1.16 0 0 1-.376.254 1.158 1.158 0 0 1-.447.085c-.16 0-.31-.028-.447-.085a1.154 1.154 0 0 1-.376-.254L1.326 8.66a.495.495 0 0 1 0-.709.493.493 0 0 1 .705 0l3.488 3.472c.04.039.079.058.118.058.039 0 .078-.02.117-.058l8.238-8.199a.495.495 0 0 1 .709.003.491.491 0 0 1-.003.705Z" />
    </svg>
  );
}

function TaskFilesIcon() {
  return (
    <svg className="task-action-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M12.654 14.497v.003h-10a1.82 1.82 0 0 1-.704-.134 1.82 1.82 0 0 1-.592-.403 1.823 1.823 0 0 1-.403-.593 1.82 1.82 0 0 1-.134-.703V3.333c0-.253.044-.487.134-.703.09-.216.224-.414.402-.593.18-.18.377-.313.593-.403.216-.09.45-.134.704-.134h2.709c.286 0 .546.055.781.165.235.11.444.275.627.495l1.067 1.28c.017.02.036.035.057.045.022.01.045.015.071.015h4.688c.253 0 .488.045.704.134.216.09.413.224.592.403.18.179.314.377.403.593.09.216.134.45.134.703V7.23a2 2 0 0 1 .272.275c.184.224.307.463.37.716.064.254.067.523.01.806l-.8 4c-.043.214-.117.41-.223.586a1.822 1.822 0 0 1-.412.473c-.17.138-.35.242-.544.311-.16.057-.329.09-.506.1ZM1.821 11.09V3.333c0-.278.069-.486.208-.625.139-.139.347-.208.625-.208h2.709c.13 0 .248.025.355.075.107.05.202.125.285.225L7.07 4.08c.117.14.25.245.399.315.15.07.315.105.497.105h4.688c.278 0 .486.07.625.208.139.14.208.348.208.625v1.505a2.13 2.13 0 0 0-.146-.005H4.29c-.481 0-.87.117-1.168.351-.297.234-.502.586-.614 1.054L1.82 11.09Zm12.338-2.26a.826.826 0 0 0-.005-.366.828.828 0 0 0-.168-.326.827.827 0 0 0-.286-.228.828.828 0 0 0-.358-.077H4.288c-.219 0-.396.054-.53.16-.136.106-.229.266-.28.479l-.962 4a.828.828 0 0 0-.009.374c.026.118.08.23.164.336.084.106.18.186.289.239.11.053.231.079.366.079h9.214c.228 0 .41-.056.546-.168.137-.111.227-.279.272-.502l.8-4Z" />
    </svg>
  );
}

function FolderPanelIcon() {
  return (
    <svg className="file-group-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M1.167 3.333c0-.253.044-.487.134-.703.09-.216.224-.414.403-.593.179-.18.376-.313.592-.403.216-.09.45-.134.704-.134h2.709c.286 0 .546.055.781.165.235.11.444.275.627.495l1.067 1.28c.017.02.036.035.057.045.022.01.045.015.071.015H13c.253 0 .488.045.704.134.216.09.413.224.592.403.18.18.314.377.403.593.09.216.134.45.134.704v7.333c0 .253-.044.487-.134.703-.09.216-.224.414-.403.593-.179.18-.376.313-.592.403-.216.09-.45.134-.704.134H3c-.253 0-.488-.044-.704-.134a1.815 1.815 0 0 1-.592-.403 1.822 1.822 0 0 1-.403-.593 1.821 1.821 0 0 1-.134-.703V3.333Zm1.06-.32a.828.828 0 0 0-.06.32v3.574h11.666V5.333a.828.828 0 0 0-.06-.32.826.826 0 0 0-.184-.269.83.83 0 0 0-.27-.183A.83.83 0 0 0 13 4.5H8.312c-.182 0-.348-.035-.497-.105a1.156 1.156 0 0 1-.399-.315L6.349 2.8a.829.829 0 0 0-.285-.225.83.83 0 0 0-.355-.075H3a.826.826 0 0 0-.32.061.83.83 0 0 0-.27.183.826.826 0 0 0-.182.27Zm11.606 4.894H2.167v4.76c0 .115.02.221.06.32.041.098.102.188.184.269a.83.83 0 0 0 .269.183c.098.04.205.061.32.061h10c.115 0 .222-.02.32-.061a.83.83 0 0 0 .27-.183.826.826 0 0 0 .182-.27.828.828 0 0 0 .061-.32v-4.76Z" />
    </svg>
  );
}

function FileGroupChevronIcon({ collapsed }) {
  return (
    <svg className="file-group-chevron" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d={collapsed ? "m6 3.75 4.25 4.25L6 12.25" : "m3.75 6 4.25 4.25L12.25 6"} stroke="#8F9299" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ReadFileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M10.152.857a.487.487 0 0 1 .2.124l3.324 3.323a.487.487 0 0 1 .156.407v8.623c0 .253-.044.488-.134.704-.09.216-.224.414-.403.593a1.821 1.821 0 0 1-.592.402c-.216.09-.45.135-.704.135h-8c-.253 0-.488-.045-.704-.134a1.823 1.823 0 0 1-.592-.403 1.82 1.82 0 0 1-.403-.593 1.822 1.822 0 0 1-.134-.704V2.668c0-.254.044-.488.134-.704.09-.216.224-.414.403-.593A1.82 1.82 0 0 1 3.295.97c.216-.09.45-.135.704-.135h5.956a.49.49 0 0 1 .197.023Zm2.68 4.31v8.167c0 .278-.069.486-.208.625-.139.14-.347.209-.625.209h-8c-.278 0-.486-.07-.625-.209-.139-.139-.208-.347-.208-.625V2.668c0-.278.07-.487.208-.625.139-.14.347-.209.625-.209h5.5v2.167c0 .161.028.31.085.448.057.137.143.263.257.377.114.114.24.2.377.256.137.057.287.086.448.086h2.166ZM10.5 4.002v-1.46l1.626 1.627h-1.46c-.055 0-.096-.014-.124-.042-.028-.028-.042-.07-.042-.125Zm-.132 3.317H5.634a.491.491 0 0 0-.5.5.49.49 0 0 0 .277.45.488.488 0 0 0 .223.05h4.733a.492.492 0 0 0 .5-.5.491.491 0 0 0-.5-.5ZM5.634 9.684h4.733a.491.491 0 0 0 .5-.5.49.49 0 0 0-.278-.449.488.488 0 0 0-.222-.05H5.634a.492.492 0 0 0-.5.5.491.491 0 0 0 .5.5Z" />
    </svg>
  );
}

function WriteFileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M9.751 1.494c-.207.109-.391.26-.553.454l-6.971 8.364a1.821 1.821 0 0 0-.415.982l-.261 2.48a.826.826 0 0 0 .05.404c.05.121.132.23.246.324a.828.828 0 0 0 .364.182.827.827 0 0 0 .406-.024l2.393-.714c.177-.052.34-.127.486-.224.148-.098.28-.217.399-.359l6.97-8.362c.162-.194.277-.404.347-.627.07-.224.093-.462.07-.714a1.822 1.822 0 0 0-.199-.69 1.82 1.82 0 0 0-.456-.553l-.85-.706a1.821 1.821 0 0 0-.626-.346 1.82 1.82 0 0 0-.712-.069 1.822 1.822 0 0 0-.688.198Zm-6.756 9.458 6.971-8.364a.828.828 0 0 1 .251-.206.825.825 0 0 1 .313-.09c.115-.01.223 0 .324.031a.827.827 0 0 1 .285.158l.85.705a.83.83 0 0 1 .207.252c.05.094.08.199.09.313a.83.83 0 0 1-.032.325.83.83 0 0 1-.158.285l-6.97 8.362a.823.823 0 0 1-.402.265l-2.153.642.236-2.232a.827.827 0 0 1 .188-.446Z" />
      <path fillRule="evenodd" fill="#8F9299" d="m9.433 2.737 2.644 2.196a.492.492 0 0 1 .065.704.49.49 0 0 1-.704.065L8.795 3.507a.489.489 0 0 1-.169-.5.49.49 0 0 1 .104-.204.49.49 0 0 1 .5-.168.492.492 0 0 1 .204.103Z" />
      <path fillRule="evenodd" fill="#8F9299" d="m3.003 10.527 2.538 2.109a.49.49 0 0 1 .169.5.489.489 0 0 1-.103.204l-.002.002a.489.489 0 0 1-.499.166.487.487 0 0 1-.203-.103l-2.54-2.108a.488.488 0 0 1-.168-.5.488.488 0 0 1 .104-.204.493.493 0 0 1 .704-.065Z" />
      <path fillRule="evenodd" fill="#8F9299" d="M13.955 13.498H6.916a.49.49 0 0 0-.5.5.49.49 0 0 0 .278.45c.067.034.141.05.222.05h7.04a.49.49 0 0 0 .5-.498V14a.49.49 0 0 0-.278-.45.488.488 0 0 0-.223-.05Z" />
    </svg>
  );
}

function UploadMinioIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M8.5 10.5v3h2.75q.992-.03 1.775-.448.475-.255.873-.653.399-.399.654-.874.419-.783.448-1.775-.02-.914-.387-1.656-.223-.45-.574-.836-.373-.41-.826-.686-.68-.413-1.541-.525-.18-.869-.656-1.52-.27-.369-.633-.667-.38-.312-.811-.511Q8.857 3.019 8 3q-.86.02-1.575.35-.43.199-.808.51-.363.297-.631.664-.478.653-.658 1.523-.863.113-1.542.526-.453.276-.825.685-.35.385-.573.833Q1.02 8.834 1 9.75q.03.992.448 1.775.255.475.654.873.398.399.873.654.783.419 1.775.448H7.5v-3h-.932a.5.5 0 0 1-.385-.82l1.433-1.72a.5.5 0 0 1 .768 0l1.433 1.72a.5.5 0 0 1-.385.82H8.5Z" />
    </svg>
  );
}

function AuditIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="#8F9299" d="M9.75 10V7.437a2.983 2.983 0 0 0 1.235-2.218 3.024 3.024 0 0 0-.149-1.133A2.938 2.938 0 0 0 9.169 2.24 3.008 3.008 0 0 0 8 2.015c-.42 0-.81.075-1.17.225a2.915 2.915 0 0 0-1.667 1.846 2.908 2.908 0 0 0-.008 1.851 2.986 2.986 0 0 0 1.095 1.5V10H4a2.071 2.071 0 0 0-.887.205 1.986 1.986 0 0 0-.527.381c-.38.38-.576.851-.586 1.414h12a2.07 2.07 0 0 0-.205-.887 1.987 1.987 0 0 0-.381-.527c-.38-.38-.851-.576-1.414-.586H9.75ZM2 13v1h12v-1H2Z" />
    </svg>
  );
}

function ModelSettingsIcon() {
  return (
    <svg className="model-settings-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="m14.7 8.93-2.549 4.333a1.821 1.821 0 0 1-.66.678 1.82 1.82 0 0 1-.92.225H5.429a1.82 1.82 0 0 1-.919-.225 1.82 1.82 0 0 1-.66-.678L1.3 8.929A1.818 1.818 0 0 1 1.027 8c0-.31.09-.62.273-.93l2.55-4.333a1.82 1.82 0 0 1 .66-.678c.263-.15.57-.226.92-.226h5.14c.35 0 .657.076.92.226.263.15.484.377.661.678L14.7 7.07c.182.31.273.62.273.93 0 .31-.09.62-.273.93Zm-.862-.508A.827.827 0 0 0 13.962 8a.828.828 0 0 0-.124-.423L11.29 3.244a.827.827 0 0 0-.3-.308.827.827 0 0 0-.418-.103H5.429a.825.825 0 0 0-.418.103.825.825 0 0 0-.3.308L2.16 7.577A.828.828 0 0 0 2.039 8c0 .14.041.281.124.422l2.549 4.334c.08.137.18.24.3.308s.26.102.418.102h5.142a.83.83 0 0 0 .418-.102.83.83 0 0 0 .3-.308l2.55-4.334ZM10.167 8c0 .3-.053.576-.159.832a2.157 2.157 0 0 1-.476.7c-.211.211-.445.37-.7.476a2.152 2.152 0 0 1-.832.159c-.3 0-.576-.053-.832-.159a2.16 2.16 0 0 1-.7-.476 2.152 2.152 0 0 1-.476-.7A2.152 2.152 0 0 1 5.833 8c0-.3.053-.576.159-.832.106-.255.264-.489.476-.7.211-.212.445-.37.7-.476.256-.106.533-.159.832-.159.3 0 .576.053.832.159.255.106.489.264.7.476.211.211.37.445.476.7.106.256.159.533.159.832Zm-1 0c0-.161-.029-.31-.086-.448a1.158 1.158 0 0 0-.256-.377c-.114-.114-.24-.2-.377-.256A1.16 1.16 0 0 0 8 6.833c-.161 0-.31.029-.448.086a1.155 1.155 0 0 0-.377.256c-.114.114-.2.24-.256.377A1.16 1.16 0 0 0 6.833 8c0 .16.029.31.086.448.057.137.142.263.256.377.114.114.24.2.377.256.137.057.287.086.448.086.16 0 .31-.029.448-.086.137-.057.263-.142.377-.256.114-.114.2-.24.256-.377.057-.138.086-.287.086-.448Z" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg className="model-settings-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M15.167 8c0 .99-.175 1.907-.525 2.751a7.118 7.118 0 0 1-1.574 2.317c-.7.7-1.472 1.224-2.317 1.574A7.12 7.12 0 0 1 8 15.167c-.99 0-1.907-.175-2.751-.525a7.122 7.122 0 0 1-2.317-1.574 7.118 7.118 0 0 1-1.574-2.317 7.116 7.116 0 0 1-.525-2.75c0-.99.175-1.907.525-2.752a7.117 7.117 0 0 1 1.574-2.316c.7-.7 1.472-1.225 2.317-1.575a7.118 7.118 0 0 1 2.75-.525c.99 0 1.907.175 2.752.525.845.35 1.617.875 2.317 1.575.7.7 1.224 1.471 1.574 2.316.35.845.525 1.762.525 2.751Zm-1 0c0-.851-.15-1.64-.452-2.367A6.126 6.126 0 0 0 12.36 3.64a6.124 6.124 0 0 0-1.993-1.355A6.125 6.125 0 0 0 8 1.833c-.852 0-1.64.151-2.367.452A6.124 6.124 0 0 0 3.639 3.64a6.124 6.124 0 0 0-1.354 1.993A6.126 6.126 0 0 0 1.833 8c0 .852.15 1.64.452 2.367a6.125 6.125 0 0 0 1.354 1.994 6.124 6.124 0 0 0 1.994 1.354A6.123 6.123 0 0 0 8 14.167c.851 0 1.64-.15 2.367-.452a6.124 6.124 0 0 0 1.993-1.354 6.124 6.124 0 0 0 1.355-1.994A6.125 6.125 0 0 0 14.167 8ZM8.4 8.244h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4.5a.5.5 0 0 1 1 0v4Z" />
    </svg>
  );
}

function TaskUpdateIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M12.078 4.328c.326.365.602.774.828 1.228a.495.495 0 0 0 .668.226h.002a.495.495 0 0 0 .226-.669v-.002a6.49 6.49 0 0 0-.981-1.453 6.499 6.499 0 0 0-1.373-1.155 6.444 6.444 0 0 0-1.611-.738 6.476 6.476 0 0 0-1.86-.265c-.667 0-1.305.095-1.913.284a6.341 6.341 0 0 0-1.537.72 6.484 6.484 0 0 0-1.38 1.184V2.667a.49.49 0 0 0-.5-.5.49.49 0 0 0-.5.5v2.632a.492.492 0 0 0 .19.43c.025.02.053.037.082.051l.005.003h.001c.035.017.07.03.109.038a.467.467 0 0 0 .154.012h2.219a.495.495 0 0 0 .5-.497v-.003a.495.495 0 0 0-.498-.5H3.52a5.406 5.406 0 0 1 1.546-1.486 5.34 5.34 0 0 1 1.28-.602A5.396 5.396 0 0 1 7.977 2.5c.55 0 1.077.076 1.581.227.472.14.923.348 1.355.621.441.28.83.606 1.165.98Zm-8.984 6.116c.226.454.502.863.828 1.228.335.374.724.7 1.165.98.432.273.883.48 1.355.621a5.478 5.478 0 0 0 1.581.227c.57 0 1.113-.082 1.631-.245.446-.14.872-.34 1.28-.602a5.476 5.476 0 0 0 1.546-1.486h-1.387a.49.49 0 0 1-.449-.277.488.488 0 0 1-.05-.223.491.491 0 0 1 .5-.5h2.219a.493.493 0 0 1 .263.05.491.491 0 0 1 .204.185.492.492 0 0 1 .073.305v2.629a.495.495 0 0 1-.5.497h-.002a.495.495 0 0 1-.498-.5v-1.02a6.415 6.415 0 0 1-1.38 1.182 6.33 6.33 0 0 1-1.537.72 6.39 6.39 0 0 1-1.913.285 6.47 6.47 0 0 1-1.86-.265 6.444 6.444 0 0 1-1.61-.738 6.5 6.5 0 0 1-1.374-1.155 6.49 6.49 0 0 1-.98-1.453.49.49 0 0 1 .048-.525.487.487 0 0 1 .177-.145.49.49 0 0 1 .526.048c.06.045.108.104.144.177Z" />
    </svg>
  );
}

function ThinkingIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M0 0h16v16H0z" />
      <path fillRule="evenodd" fill="currentColor" d="M8 1c.146 0 .266.047.36.14.093.094.14.214.14.36v3a.487.487 0 0 1-.14.36A.487.487 0 0 1 8 5a.487.487 0 0 1-.36-.14.487.487 0 0 1-.14-.36v-3c0-.146.047-.266.14-.36A.487.487 0 0 1 8 1Zm0 10c.146 0 .266.047.36.14.093.094.14.214.14.36v3a.487.487 0 0 1-.14.36A.487.487 0 0 1 8 15a.487.487 0 0 1-.36-.14.487.487 0 0 1-.14-.36v-3c0-.146.047-.266.14-.36A.487.487 0 0 1 8 11Zm7-3a.487.487 0 0 1-.14.36.487.487 0 0 1-.36.14h-3a.487.487 0 0 1-.36-.14A.487.487 0 0 1 11 8c0-.146.047-.266.14-.36a.487.487 0 0 1 .36-.14h3c.146 0 .266.047.36.14.093.094.14.214.14.36ZM5 8a.487.487 0 0 1-.14.36.487.487 0 0 1-.36.14h-3a.487.487 0 0 1-.36-.14A.487.487 0 0 1 1 8c0-.146.047-.266.14-.36a.487.487 0 0 1 .36-.14h3c.146 0 .266.047.36.14.093.094.14.214.14.36ZM3.047 3.047a.522.522 0 0 1 .36-.14c.135 0 .25.046.343.14l2.125 2.125c.094.104.141.222.141.351 0 .13-.05.245-.148.344a.47.47 0 0 1-.344.15.516.516 0 0 1-.352-.142L3.047 3.75a.468.468 0 0 1-.14-.344.52.52 0 0 1 .14-.359Zm7.078 7.078a.487.487 0 0 1 .351-.156c.13 0 .248.052.352.156l2.125 2.125c.094.094.14.208.14.344a.48.48 0 0 1-.148.352.482.482 0 0 1-.351.148.467.467 0 0 1-.345-.14l-2.125-2.125a.486.486 0 0 1-.156-.352c0-.13.052-.247.156-.351l.001-.001Zm2.828-7.078c.094.104.14.224.14.36a.47.47 0 0 1-.14.343l-2.125 2.125a.513.513 0 0 1-.352.141.473.473 0 0 1-.344-.149.47.47 0 0 1-.148-.344c0-.13.047-.247.14-.35l2.125-2.126a.468.468 0 0 1 .345-.14c.135 0 .255.046.359.14Zm-7.078 7.078a.485.485 0 0 1 .156.352c0 .13-.052.247-.156.35L3.75 12.954a.468.468 0 0 1-.344.14.48.48 0 0 1-.352-.148.484.484 0 0 1-.148-.351c0-.136.047-.25.14-.345l2.126-2.125a.486.486 0 0 1 .351-.156c.13 0 .247.052.352.156v.001Z" />
    </svg>
  );
}

function CommandIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M30.4417 5C32.406 5 34.265 5.44776 35.9207 6.24607L32.7172 9.42668C30.8706 11.2601 30.8706 14.2327 32.7172 16.0661C34.5638 17.8995 37.5578 17.8995 39.4044 16.0661L42.2571 13.2337C42.7379 14.5558 43 15.9818 43 17.4685C43 24.3547 37.3775 29.937 30.4417 29.937C28.7825 29.937 27.1985 29.6176 25.7486 29.0373L13.07 41.6253C11.2238 43.4582 8.2307 43.4582 6.38459 41.6253C4.53847 39.7924 4.53847 36.8207 6.38459 34.9877L18.9523 22.5099C18.2651 20.9684 17.8834 19.2627 17.8834 17.4685C17.8834 10.5823 23.5059 5 30.4417 5Z" fill="none" stroke="currentColor" strokeWidth="4" strokeLinejoin="round" />
    </svg>
  );
}

function isExpiredApprovalError(error) {
  const text = String(error || "");
  return /没有待确认.*(?:请求|操作)|请求已过期/.test(text);
}

function normalizeFiles(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => (typeof item === "string" ? item : item?.path || item?.filename)).filter(Boolean);
}

function eventClock(event) {
  const raw = event?._receivedAt ?? event?.timestamp;
  if (raw == null || raw === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return value > 1e11 ? value : value > 1e9 ? value * 1000 : value;
}

function stampEvent(event) {
  if (!event || typeof event !== "object") return { type: "text", text: String(event ?? ""), _receivedAt: Date.now() };
  const clock = eventClock(event);
  return clock == null ? { ...event, _receivedAt: Date.now() } : { ...event, _receivedAt: clock };
}

function normalizeEvents(task) {
  const source = Array.isArray(task?.log) ? task.log : Array.isArray(task?.events) ? task.events : [];
  return source.reduce((events, event) => {
    if (!event || typeof event !== "object") {
      events.push({ type: "text", text: String(event ?? "") });
      return events;
    }
    const content = event.text ?? event.content;
    const normalized = { ...event, text: typeof content === "string" ? content : content == null ? "" : $json(content) };
    const last = events[events.length - 1];
    if ((normalized.type === "text" || normalized.type === "thinking") && last?.type === normalized.type) {
      events[events.length - 1] = { ...last, text: `${last.text || ""}${normalized.text || ""}` };
    } else {
      events.push(normalized);
    }
    return events;
  }, []);
}

function formatDuration(durationMs) {
  const milliseconds = Math.max(0, Number(durationMs) || 0);
  if (milliseconds < 1000) return `${Math.max(1, Math.round(milliseconds))}ms`;
  const seconds = milliseconds / 1000;
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

function eventDuration(events, index) {
  const event = events[index];
  const start = eventClock(event);
  if (start == null || ["done", "tool_result", "approval_result", "audit", "error"].includes(event.type)) return null;
  let endEvent = null;
  if (event.type === "tool_use" && event.id) {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type === "tool_result" && candidate.tool_use_id === event.id);
  } else if (event.type === "approval_request" && event.id) {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type === "approval_result" && candidate.id === event.id);
  } else if (event.type === "thinking") {
    endEvent = events.slice(index + 1).find((candidate) => candidate.type !== "thinking");
  } else {
    endEvent = events[index + 1];
  }
  const end = eventClock(endEvent);
  return end != null && end > start ? end - start : null;
}

function eventTitle(event) {
  const names = { Read: "读取文件", Write: "写入文件", Edit: "修改文件", Bash: "执行命令", Glob: "查找文件", Grep: "搜索内容", Agent: "调用子智能体", TaskCreate: "创建任务" };
  if (event.type === "thinking") return "思考中";
  if (event.type === "model_switch") return "模型切换";
  if (event.type === "tool_result") return "工具结果";
  return names[event.name] || event.name || event.type || "执行步骤";
}

function eventStatus(event) {
  if (event.type === "error" || event.is_error) return "error";
  if (event.type === "approval_request") return "warning";
  if (event.type === "done" || event.type === "approval_result") return "success";
  return "process";
}

function eventDescription(event) {
  if (event.type === "thinking" || event.type === "text" || event.type === "assistant") return event.text || "";
  if (event.type === "tool_result") return String(event.content || "").slice(0, 1200);
  if (event.type === "error") return event.error || "执行失败";
  if (event.type === "approval_request") return `${event.summary || "需要确认"}${event.detail ? `：${event.detail}` : ""}`;
  if (event.type === "approval_result") return event.approved ? "已允许执行" : "已拒绝执行";
  if (event.type === "model_switch") return `${event.from || "当前模型"} → ${event.to || "备用模型"}（${event.reason || "自动切换"}）`;
  if (event.input) return typeof event.input === "string" ? event.input : $json(event.input);
  return event.text || "";
}

function EventFileText({ text, files, onFile }) {
  const source = String(text || "");
  const paths = (files || []).map((file) => file.path).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!paths.length || !onFile) return <>{source}</>;
  const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(`(${paths.map(escapeRegExp).join("|")})`, "g");
  return <>{source.split(pattern).map((part, index) => paths.includes(part)
    ? <button type="button" className="event-file-link" key={`${part}-${index}`} onClick={(clickEvent) => { clickEvent.stopPropagation(); onFile(part); }}>{part}</button>
    : <React.Fragment key={index}>{part}</React.Fragment>)}</>;
}

function compactEventSummary(value) {
  const source = String(value || "");
  const trimmed = source.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      const first = Array.isArray(parsed) ? parsed[0] : Object.entries(parsed)[0];
      if (Array.isArray(first)) return `${first[0]}: ${typeof first[1] === "string" ? first[1] : JSON.stringify(first[1])}`;
      if (first !== undefined) return typeof first === "string" ? first : JSON.stringify(first);
    } catch { /* 多行非标准 JSON，继续按首行处理 */ }
  }
  const firstLine = trimmed.split(/\r?\n/).map((line) => line.trim()).find((line) => line && !/^[{}[\],]+$/.test(line)) || "";
  return firstLine.replace(/^[{"'`\s]+|[}"'`,\s]+$/g, "").replace(/^([^:]+):\s*["']?(.*?)["']?$/, "$1: $2");
}

function ThoughtEvent({ event, onApprove, files, onFile, loading = false, approvalResult = null, completed = false, durationMs = null }) {
  const [expanded, setExpanded] = useState(false);
  const isReadTool = event.type === "tool_use" && event.name === "Read";
  const isWriteTool = event.type === "tool_use" && event.name === "Write";
  const isEditTool = event.type === "tool_use" && event.name === "Edit";
  const isAudit = event.type === "audit";
  const isTaskUpdate = event.type === "tool_use" && event.name === "TaskUpdate";
  const isCommand = event.type === "tool_use" && event.name === "Bash";
  const kind = event.type === "thinking" ? "thinking" : event.type === "model_switch" ? "model-switch" : event.type === "tool_result" ? "tool-result" : event.type === "approval_result" ? "approval-result" : event.type === "error" || event.is_error ? "error" : event.name === "TaskCreate" ? "task-create" : event.type === "approval_request" ? "approval" : isReadTool ? "read-file" : isWriteTool ? "write-file" : isEditTool ? "edit-file" : isAudit ? "audit" : isTaskUpdate ? "task-update" : isCommand ? "command" : "tool-use";
  const icon = event.type === "thinking" ? <ThinkingIcon /> : event.type === "model_switch" ? "↻" : event.type === "tool_result" ? "✓" : event.type === "approval_result" && event.approved ? "✓" : event.type === "error" || event.is_error ? "!" : event.name === "TaskCreate" ? "＋" : event.type === "approval_request" ? "?" : isReadTool ? <ReadFileIcon /> : isWriteTool || isEditTool ? <WriteFileIcon /> : isAudit ? <AuditIcon /> : isTaskUpdate ? <TaskUpdateIcon /> : isCommand ? <CommandIcon /> : "·";
  const detail = eventDescription(event);
  const approved = event.type === "approval_request" && approvalResult?.approved === true;
  const durationLabel = durationMs != null && !loading ? event.type === "thinking" ? `已思考 ${formatDuration(durationMs)}` : formatDuration(durationMs) : "";
  const toggleExpanded = () => setExpanded((value) => !value);
  const collapsedRowProps = {
    className: "thought-collapsed-row thought-collapsed-row-clickable",
    onClick: toggleExpanded,
    onKeyDown: (keyboardEvent) => {
      if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
        keyboardEvent.preventDefault();
        toggleExpanded();
      }
    },
    role: "button",
    tabIndex: 0,
  };
  return (
    <div className={`chain-event chain-event-${kind}`}>
      <div {...collapsedRowProps}>
        <div className="thought-header">
          <span className={`thought-icon thought-icon-${kind}`}>{icon}</span>
          <button type="button" className="thought-toggle" onClick={(clickEvent) => { clickEvent.stopPropagation(); toggleExpanded(); }}>{eventTitle(event)}</button>
        </div>
        {!expanded && detail && <div className="thought-summary"><EventFileText text={compactEventSummary(detail)} files={files} onFile={onFile} /></div>}
        {durationLabel && <span className="thought-duration">{durationLabel}</span>}
      </div>
      {expanded && <div className="thought-detail"><EventFileText text={detail} files={files} onFile={onFile} /></div>}
      {event.type === "approval_request" && !completed && (
        <div className="approval-actions">
          {approved ? <Button type="primary" size="small" disabled>✓ 已允许执行</Button> : <>
            <Button type="primary" size="small" onClick={() => onApprove(event.id, true)}>允许执行</Button>
            <Button size="small" onClick={() => onApprove(event.id, false)}>拒绝</Button>
          </>}
        </div>
      )}
    </div>
  );
}

function inlineMarkdown(value) {
  const text = String(value || "");
  const token = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^\)]+\))/g;
  return text.split(token).map((part, index) => {
    if (/^\*\*.*\*\*$|^__.*__$/.test(part)) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (/^\*.*\*$|^_.*_$/.test(part)) return <em key={index}>{part.slice(1, -1)}</em>;
    if (/^`.*`$/.test(part)) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\(([^\)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <React.Fragment key={index}>{part.split("\n").map((line, lineIndex) => <React.Fragment key={lineIndex}>{lineIndex ? <br /> : null}{line}</React.Fragment>)}</React.Fragment>;
  });
}

function markdownTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function AssistantText({ text }) {
  const lines = String(text || "").split("\n");
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) { index += 1; continue; }
    if (/^```/.test(trimmed)) {
      const code = []; index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(<pre className="markdown-code" key={`code-${index}`}><code>{code.join("\n")}</code></pre>); continue;
    }
    if (/^\|/.test(trimmed) && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const head = markdownTableRow(line); index += 2; const rows = [];
      while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(markdownTableRow(lines[index++]));
      blocks.push(<table className="markdown-table" key={`table-${index}`}><thead><tr>{head.map((cell, cellIndex) => <th key={cellIndex}>{inlineMarkdown(cell)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{head.map((_, cellIndex) => <td key={cellIndex}>{inlineMarkdown(row[cellIndex] || "")}</td>)}</tr>)}</tbody></table>); continue;
    }
    if (/^#{1,3}\s/.test(trimmed)) { blocks.push(<h3 key={`heading-${index}`}>{inlineMarkdown(trimmed.replace(/^#{1,3}\s*/, ""))}</h3>); index += 1; continue; }
    if (/^[-*]\s/.test(trimmed)) { const items = []; while (index < lines.length && /^\s*[-*]\s/.test(lines[index])) items.push(lines[index++].replace(/^\s*[-*]\s+/, "")); blocks.push(<ul key={`list-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inlineMarkdown(item)}</li>)}</ul>); continue; }
    const paragraph = [line]; index += 1;
    while (index < lines.length && lines[index].trim() && !/^```|^#{1,3}\s|^\s*[-*]\s|^\s*\|/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(paragraph.join("\n"))}</p>);
  }
  return <div className="assistant-text">{blocks}</div>;
}

function EventFeed({ events, onApprove, files, onFile, busy = false }) {
  const lastEvent = events[events.length - 1];
  const waitingForNextEvent = busy && !["done", "error", "approval_request"].includes(lastEvent?.type);
  const approvalResults = events.reduce((result, event) => {
    if (event.type === "approval_result" && event.id) result[event.id] = event;
    return result;
  }, {});
  return (
    <div className="feed-list">
      {events.map((event, index) => {
        if (event.type === "user") return <div className="user-message" key={`${index}-user`}>{event.text}</div>;
        if (["text", "assistant"].includes(event.type)) return <div className="assistant-message" key={`${index}-assistant`}><AssistantText text={event.text} /></div>;
        if (event.type === "done") return <div className="done-note" key={`${index}-done`}>本轮执行结束 · {event.status || "完成"}</div>;
        const loading = busy && index === events.length - 1 && event.type === "thinking";
        const executionFinished = event.type === "approval_request" && events.slice(index + 1).some((candidate) => candidate.type === "done");
        return <ThoughtEvent event={event} approvalResult={event.type === "approval_request" ? approvalResults[event.id] : null} completed={executionFinished} durationMs={eventDuration(events, index)} onApprove={onApprove} files={files} onFile={onFile} loading={loading} key={`${index}-${event.id || event.type}`} />;
      })}
      {waitingForNextEvent && lastEvent?.type !== "thinking" && (
        <ThoughtEvent event={{ type: "thinking", text: "" }} files={files} onFile={onFile} loading />
      )}
    </div>
  );
}

function parseCsv(text) {
  const source = String(text || "").replace(/^\uFEFF/, "");
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(cell); cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); if (row.some((value) => value !== "")) rows.push(row); }
  return rows;
}

function CsvPreview({ text }) {
  const rows = parseCsv(text);
  const headers = rows[0] || [];
  const body = rows.slice(1);
  return <div className="csv-preview"><div className="csv-preview-meta">CSV 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th key={index}>{header || `列 ${index + 1}`}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] || ""}</td>)}</tr>)}</tbody></table></div></div>;
}

function SpreadsheetPreview({ sheets }) {
  const [active, setActive] = useState(0);
  const current = sheets[active] || { name: "Sheet1", rows: [] };
  const headers = current.rows[0] || [];
  const body = current.rows.slice(1);
  return <div className="csv-preview"><div className="sheet-tabs">{sheets.map((sheet, index) => <button type="button" className={index === active ? "sheet-tab active" : "sheet-tab"} key={sheet.name} onClick={() => setActive(index)}>{sheet.name}</button>)}</div><div className="csv-preview-meta">Excel 表格预览 · {body.length} 行 · {headers.length} 列</div><div className="csv-preview-scroll"><table className="csv-preview-table"><thead><tr>{headers.map((header, index) => <th key={index}>{String(header || `列 ${index + 1}`)}</th>)}</tr></thead><tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, columnIndex) => <td key={columnIndex}>{String(row[columnIndex] ?? "")}</td>)}</tr>)}</tbody></table></div></div>;
}

function formatFileSize(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0B";
  if (bytes < 1000) return `${bytes}B`;
  const units = ["K", "M", "G"]; let size = bytes; let index = -1;
  while (size >= 1000 && index < units.length - 1) { size /= 1000; index += 1; }
  return `${size.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1")}${units[index]}`;
}

const MISSION_LABELS = {
  repositoryId: "本体库 ID", taskCode: "任务编码", taskName: "任务名称", modelName: "模型名称",
  taskType: "任务类型", prompt: "提示词", parseElements: "解析要素", expectedFiles: "期望输出文件",
  outputPrefix: "输出路径前缀", sourceMode: "来源模式", checkTypes: "校验类型", dbType: "数据库类型",
  host: "主机", port: "端口", database: "数据库", username: "用户名", password: "密码",
  sourceSchema: "Schema", selectedTables: "选中数据表", databaseSourceId: "数据源 ID",
  fileSourceId: "文件源 ID", fileType: "文件类型", objectKey: "对象存储 Key", items: "条目",
  mode: "模式", generateAlignmentReport: "生成对齐报告", generate_alignment_report: "生成对齐报告",
  autoMergeStrategy: "自动合并策略", auto_merge_strategy: "自动合并策略", alignmentStrategy: "对齐策略",
  mergeStrategy: "整合策略", conflictResolutionStrategy: "冲突处理策略", pendingConfirmationStrategy: "待确认策略",
  modelingPlan: "分层建模计划", identity: "任务身份", artifacts: "Artifact 清单",
  artifactType: "Artifact 类型", layer: "层级", requested: "是否请求", source: "来源",
  status: "状态", dependsOn: "依赖", outputs: "输出文件", key: "身份键",
  modelVersion: "模型版本", inputFingerprint: "输入指纹", requestedElements: "请求解析要素",
  executionOrder: "执行顺序", valid: "依赖校验通过", dependencyErrors: "依赖错误",
};
const MISSION_SECTION_LABELS = {
  database: "数据源", document: "文档", sourceModels: "来源模型", integrationStrategy: "整合策略",
  validationRules: "校验规则",
};
const missionLabel = (key) => MISSION_LABELS[key] || MISSION_SECTION_LABELS[key] || key;

function RecursiveInfo({ value, level = 0, field = "" }) {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) return <div className="info-tags">{value.map((item, index) => <Tag key={index}>{typeof item === "object" ? $json(item) : String(item)}</Tag>)}</div>;
  if (typeof value === "object") return <div className="info-nested">{Object.entries(value).map(([key, item]) => <div className="info-row" key={`${level}-${key}`}><span className="info-key">{missionLabel(key)}</span><div className="info-value"><RecursiveInfo value={item} level={level + 1} field={key} /></div></div>)}</div>;
  return <span>{field === "password" ? "••••••••" : String(value)}</span>;
}

function MissionInfo({ open, context, loading, onClose }) {
  return (
    <Modal open={open} title="当前任务信息" footer={null} onCancel={onClose} width={680} destroyOnClose>
      {loading ? <Spin /> : context ? <div className="mission-info"><RecursiveInfo value={context} /></div> : <Empty description="暂未获取到任务信息" />}
    </Modal>
  );
}

function SettingsModal({ open, onClose, meta, model, onModel, params, onParams, provider, keyValue, setKeyValue, onSaveKey }) {
  const models = (meta?.models || []).map((item) => ({ value: item.id, label: `${item.label || item.id} · ${item.provider || ""}` }));
  return (
    <Modal open={open} title="大语言模型设置" footer={null} onCancel={onClose} width={560}>
      <div className="settings-section"><div className="settings-label">模型</div><Select showSearch value={model} options={models} onChange={onModel} /></div>
      <Divider />
      <div className="settings-section"><div className="settings-label">模型参数</div>
        <div className="settings-grid">
          <label>最大输出 token<InputNumber min={1} value={params.max_tokens} onChange={(value) => onParams({ max_tokens: value })} /></label>
          <label>温度<Slider min={0} max={2} step={0.1} value={params.temperature ?? 0} onChange={(value) => onParams({ temperature: value })} /></label>
          <label>扩展思考<Switch checked={Boolean(params.thinking)} onChange={(value) => onParams({ thinking: value })} /></label>
          <label>思考预算 token<InputNumber min={1024} step={512} value={params.thinking_budget} onChange={(value) => onParams({ thinking_budget: value })} /></label>
        </div>
      </div>
      <Divider />
      <div className="settings-section"><div className="settings-label">当前用户模型密钥 · {provider || "—"}</div>
        <Input.Password value={keyValue} onChange={(event) => setKeyValue(event.target.value)} placeholder="粘贴该模型对应的 API Key" addonAfter={<Button type="link" onClick={onSaveKey}>保存</Button>} />
      </div>
    </Modal>
  );
}

function ModelPicker({ model, models, onModel, onOpenSettings }) {
  const [open, setOpen] = useState(false);
  const content = <div className="model-picker">
    <div className="model-picker-list">{(models || []).map((item) => <button type="button" className={item.id === model ? "model-option active" : "model-option"} key={item.id} onClick={() => { onModel(item.id); setOpen(false); }}><span>{item.label || item.id}</span><small>{item.provider || ""}</small></button>)}</div>
    <Button type="link" className="model-params-link" onClick={() => { setOpen(false); onOpenSettings(); }}><ModelSettingsIcon /> 修改模型参数</Button>
  </div>;
  const modelText = String(model || "模型");
  return <Popover open={open} onOpenChange={setOpen} trigger="click" placement="topRight" content={content} title="选择大语言模型"><button type="button" className="model-hint" aria-label={`当前模型：${model || "未选择"}`} title={model || "未选择模型"}><span className="model-name"><ModelSettingsIcon /> {modelText.length > 15 ? `${modelText.slice(0, 15)}...` : modelText}</span></button></Popover>;
}

function Composer({ value, onChange, onSend, onAttach, pendingFiles, mission, busy, hasConversation, model, models, onModel, onOpenSettings, placeholder, projects, project, onProject, autoApprove, onToggleAutoApprove, showAutoApprove = false }) {
  const start = mission && !hasConversation && !value.trim();
  return (
    <div className="composer">
      <Input.TextArea value={value} onChange={(event) => onChange(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); onSend(); } }} autoSize={{ minRows: 1, maxRows: 8 }} placeholder={placeholder} disabled={busy} />
      {!!pendingFiles.length && <div className="pending-files">{pendingFiles.map((file) => <Tag key={file.name}>📎 {file.name}</Tag>)}</div>}
      <div className="composer-row">
        <Button type="text" onClick={onAttach} title="上传文件到项目"><UploadFileIcon /> <span>上传文件</span></Button>
        {showAutoApprove && <Button className="auto-approve-toggle" type={autoApprove ? "primary" : "default"} aria-pressed={autoApprove} title="切换自动确认" onClick={onToggleAutoApprove}>{autoApprove ? "自动确认：开" : "自动确认：关"}</Button>}
        {!mission && projects?.length > 0 && <Select size="small" value={project} options={projects.map((item) => ({ value: item.name, label: item.name }))} onChange={onProject} className="project-select" placeholder="选择项目" />}
        <ModelPicker model={model} models={models} onModel={onModel} onOpenSettings={onOpenSettings} />
        <Button type={start ? "primary" : "default"} className={start ? "start-button" : "send-button"} onClick={onSend} disabled={busy}>{start ? (mission?.taskType === "integration" ? "开始智能消歧与整合" : "开始智能建模") : <SendArrowIcon />}</Button>
      </div>
    </div>
  );
}

function FilePanel({ open, files, loading, selected, onSelect, onSelectGroup, onOpen, onDownload, onUploadToMinio, uploadingToMinio, uploadBlocked = false, onClose, onRefresh, mission, focusPath, platformStatus, resetKey }) {
  const defaultCollapsedDirs = () => new Set(["", "mission-input", "mission-work"]);
  const [collapsedDirs, setCollapsedDirs] = useState(defaultCollapsedDirs);
  // The panel has exactly four top-level scopes.  Nested files under
  // mission-input/output/work must never become additional directory groups.
  const displayDir = (path) => {
    const first = String(path || "").replaceAll("\\", "/").split("/")[0];
    return ["mission-input", "mission-output", "mission-work"].includes(first) ? first : "";
  };
  const groups = useMemo(() => {
    const map = new Map();
    if (mission) {
      ["mission-input", "mission-output", "mission-work"].forEach((dir) => map.set(dir, []));
    }
    files.forEach((file) => { const dir = displayDir(file.path); if (!map.has(dir)) map.set(dir, []); map.get(dir).push(file); });
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [files, mission]);
  const toggleDir = (dir) => setCollapsedDirs((current) => {
    const next = new Set(current);
    if (next.has(dir)) next.delete(dir); else next.add(dir);
    return next;
  });
  const groupLabel = (dir) => <><FolderPanelIcon /> {dir ? `${dir}/` : "项目根目录"}</>;
  useEffect(() => {
    if (!open) return;
    // Every open/session switch starts with only mission-output expanded.
    setCollapsedDirs(defaultCollapsedDirs());
  }, [open, resetKey]);
  if (!open) return null;
  return <aside className="file-panel">
    <div className="panel-head"><strong>项目文件</strong><Button size="small" aria-label="刷新文件" title="刷新文件" onClick={onRefresh}><RefreshFilePanelIcon /></Button><Button size="small" aria-label="折叠文件面板" title="折叠文件面板" onClick={onClose}><CollapseFilePanelIcon /></Button></div>
    <div className="file-actions"><Button size="small" icon={<DownloadSelectedIcon />} disabled={!selected.length} onClick={onDownload}>下载所选</Button>{mission && <Tooltip title={uploadBlocked ? "任务执行或状态变更期间不能上传" : platformStatus === "COMPLETED" ? "上传新结果将恢复任务为执行中" : "上传选中的任务结果"}><Button size="small" type="primary" icon={<UploadMinioIcon />} loading={uploadingToMinio} disabled={!selected.length || uploadingToMinio || uploadBlocked} onClick={onUploadToMinio}>上传到 MinIO</Button></Tooltip>}{mission && <span className="panel-note">{platformStatus === "COMPLETED" ? "上传新结果将恢复执行" : "当前任务范围"}</span>}</div>
    {loading ? <Spin /> : !files.length && !mission ? <Empty description="暂无文件" /> : <div className="file-list">{groups.map(([dir, items]) => {
      const collapsed = collapsedDirs.has(dir);
      const paths = items.map((file) => file.path);
      const allSelected = paths.length > 0 && paths.every((path) => selected.includes(path));
      const partiallySelected = !allSelected && paths.some((path) => selected.includes(path));
      return <div className="file-group" key={dir || "root"}>
        <div className="file-group-title">
          <input className="folder-select" type="checkbox" checked={allSelected} ref={(node) => { if (node) node.indeterminate = partiallySelected; }} onChange={() => onSelectGroup(paths)} aria-label={`选择 ${dir || "项目根目录"} 下全部文件`} />
          <button type="button" className="file-group-toggle" onClick={() => toggleDir(dir)} aria-expanded={!collapsed}><FileGroupChevronIcon collapsed={collapsed} /> {groupLabel(dir)}</button>
          <span>({items.length})</span>
        </div>
        {!collapsed && (items.length ? items.map((file) => <div className={`file-row ${focusPath === file.path ? "file-row-focused" : ""}`} key={file.path}><input type="checkbox" checked={selected.includes(file.path)} onChange={() => onSelect(file.path)} /><button onClick={() => onOpen(file.path)}>{file.path.split("/").pop()}</button><small>{formatFileSize(file.size)}</small></div>) : <div className="file-group-empty">暂无文件</div>)}
      </div>;
    })}</div>}
  </aside>;
}

function App() {
  const [meta, setMeta] = useState({ models: [], projects: [], params: {} });
  const [tasks, setTasks] = useState([]);
  const [active, setActive] = useState(null);
  const [events, setEvents] = useState([]);
  const [view, setView] = useState(MISSION ? "home" : "home");
  const [text, setText] = useState("");
  const [pendingFiles, setPendingFiles] = useState([]);
  const [files, setFiles] = useState([]);
  const [filesOpen, setFilesOpen] = useState(false);
  const [filesLoading, setFilesLoading] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [focusFile, setFocusFile] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [minioUploading, setMinioUploading] = useState(false);
  const [platformActionLoading, setPlatformActionLoading] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [missionInfoOpen, setMissionInfoOpen] = useState(false);
  const [missionContext, setMissionContext] = useState(null);
  const [missionLoading, setMissionLoading] = useState(Boolean(MISSION));
  const [keyValue, setKeyValue] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [autoApprove, setAutoApprove] = useState(() => localStorage.getItem("oc_auto_approve") === "1");
  const autoApproveRef = useRef(autoApprove);
  const approvalInFlightRef = useRef(new Set());
  const previewImageUrlRef = useRef("");
  const previewRequestRef = useRef(0);
  const [messageApi, contextHolder] = message.useMessage();
  const fileInput = useRef(null);
  const feedRef = useRef(null);
  const feedPinnedRef = useRef(true);

  const model = meta.model || "";
  const params = meta.params || { temperature: null, max_tokens: null, thinking: false, thinking_budget: 8000 };
  const provider = meta.provider || "";
  const currentMission = missionIdentity(active);
  const isMissionTask = Boolean(currentMission);
  const hasConversation = Boolean(active?.hasConversation || events.some((event) => ["user", "assistant"].includes(event.type) && String(event.text || "").trim()));
  const placeholder = view === "task" ? "继续对这个任务下指令…" : MISSION ? "点击开始任务，或者描述一个任务" : "描述一个任务，例如：帮我分析这个项目…";

  const loadMeta = async () => { const result = await api("/api/meta"); if (!result.error) setMeta(result); else messageApi.error(result.error); };
  const loadTasks = async () => { const result = await api(`/api/tasks${MISSION ? `?repositoryId=${encodeURIComponent(MISSION.repositoryId)}&taskCode=${encodeURIComponent(MISSION.taskCode)}` : ""}`); if (!result.error) { setTasks(result.tasks || []); return result.tasks || []; } return []; };
  const loadMission = async (mission = MISSION) => {
    if (!mission?.repositoryId || !mission?.taskCode) return;
    setMissionLoading(true);
    const query = new URLSearchParams({ repositoryId: mission.repositoryId, taskCode: mission.taskCode, ...(mission.taskType ? { taskType: mission.taskType } : {}) });
    const result = await api(`/api/mission/task?${query}`);
    // 任务信息只是侧栏的辅助内容；上游任务已完成、删除或暂不可查时，
    // 保持空态即可，不能在打开历史对话时弹出错误打断用户。
    if (!result.error) {
      setMissionContext(result.task);
    } else {
      setMissionContext(null);
    }
    setMissionLoading(false);
    return result.error ? null : result;
  };

  useEffect(() => {
    // Mission loading also authenticates and claims compatible legacy local
    // sessions.  Serialize it before loading/opening tasks so a historical
    // conversation cannot race that ownership migration.
    const bootstrap = async () => {
      await loadMeta();
      if (MISSION) await loadMission();
      await loadTasks();
    };
    void bootstrap();
  }, []);
  useEffect(() => { if (!selectedProject && meta.projects?.length) setSelectedProject(meta.projects[0].name); }, [meta.projects, selectedProject]);
  useEffect(() => {
    if (!MISSION || !tasks.length || active) return;
    const saved = localStorage.getItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`);
    const task = tasks.find((item) => item.id === saved) || tasks[0];
    if (task) openTask(task);
  }, [tasks, active]);
  useEffect(() => { if (active && filesOpen) loadFiles(); }, [active, filesOpen]);
  useEffect(() => {
    setSelectedFiles([]);
    setFocusFile("");
    closePreview();
  }, [active?.id]);
  useEffect(() => {
    if (view !== "task" || !feedRef.current) return undefined;
    const frame = window.requestAnimationFrame(() => {
      const feed = feedRef.current;
      if (feed && feedPinnedRef.current) feed.scrollTop = feed.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [events, busy, view]);
  useEffect(() => () => {
    if (previewImageUrlRef.current) URL.revokeObjectURL(previewImageUrlRef.current);
  }, []);

  const handleFeedScroll = () => {
    const feed = feedRef.current;
    if (!feed) return;
    // Follow the live stream only while the user is already at the bottom.
    // Once they scroll up, incoming thought-chain events must not pull them
    // back down; returning to the bottom resumes live following automatically.
    feedPinnedRef.current = feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 56;
  };

  const openTask = async (task) => {
    const taskMission = missionIdentity(task);
    const detailQuery = taskMission ? `?repositoryId=${encodeURIComponent(taskMission.repositoryId)}&taskCode=${encodeURIComponent(taskMission.taskCode)}` : "";
    const result = await api(`/api/tasks/${task.id}${detailQuery}`);
    if (result.error) { messageApi.error(`打开历史会话失败：${result.error}`); return; }
    const current = { ...result };
    if (taskMission && !MISSION) {
      const missionResult = await loadMission({ ...taskMission, taskType: current.taskType || task.taskType || "" });
      if (missionResult?.platformStatus) current.platformStatus = missionResult.platformStatus;
    }
    feedPinnedRef.current = true;
    setActive(current); setEvents(normalizeEvents(current)); setView("task"); setText("");
    if (MISSION) localStorage.setItem(`oc_active_task_${MISSION.repositoryId}_${MISSION.taskCode}`, current.id);
    // 页面刷新或重新打开历史会话时，审批请求可能已经在服务端挂起，
    // 不会再次经过 SSE；自动确认开启时要主动恢复这类请求。
    if (autoApproveRef.current) {
      const pending = normalizeEvents(current).find((event) => event.type === "approval_request");
      if (pending) void approve(pending.id, true, current);
    }
    await loadFiles(current);
  };

  const loadFiles = async (task = active) => {
    setFilesLoading(true);
    const project = task?.project || "";
    const query = `/api/files?project=${encodeURIComponent(project)}${missionQuery({ taskId: task?.id || "" }, task)}`;
    const result = await api(query);
    if (!result.error) setFiles((result.files || []).filter((file) => !String(file.path).includes("-sheets/") && !String(file.path).endsWith("manifest.json")));
    setFilesLoading(false);
  };

  const createTask = async () => {
    const result = await api("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: MISSION ? "" : selectedProject || meta.projects?.[0]?.name || "", repositoryId: MISSION?.repositoryId || "", taskCode: MISSION?.taskCode || "", taskType: MISSION?.taskType || "" }) });
    if (result.error) { messageApi.error(result.error); return null; }
    feedPinnedRef.current = true;
    setTasks((previous) => [result, ...previous.filter((task) => task.id !== result.id)]); setActive(result); setEvents([]); setView("task"); return result;
  };

  const reuseMissionTask = async () => {
    const task = active || tasks[0];
    setHistoryOpen(true);
    if (!task) {
      messageApi.info("当前任务还没有本地会话，请先开始任务");
      return null;
    }
    await openTask(task);
    messageApi.success("已复用当前任务，不会新建会话");
    return task;
  };

  const handleNewSession = async () => {
    if (MISSION) {
      await reuseMissionTask();
      return;
    }
    setActive(null); setEvents([]); setText(""); setView("home");
    await createTask();
  };

  const appendEvent = (event) => setEvents((previous) => {
    event = stampEvent(event);
    if (event.type === "text" || event.type === "thinking") {
      const last = previous[previous.length - 1];
      if (last?.type === event.type) return [...previous.slice(0, -1), { ...last, text: `${last.text || ""}${event.text || ""}` }];
    }
    return [...previous, event];
  });

  const approve = async (id, approved, taskOverride = null) => {
    const task = taskOverride || active;
    if (!task || !id) return false;
    const key = `${task.id}:${id}`;
    if (approvalInFlightRef.current.has(key)) return false;
    approvalInFlightRef.current.add(key);
    try {
      const result = await api(`/api/tasks/${task.id}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, approved }) });
      if (result.error) {
        // 自动恢复历史审批时，服务端可能已处理同一个请求；这不是用户需要
        // 处理的异常。其他审批失败（鉴权、网络等）仍然保留明确提示。
        if (!isExpiredApprovalError(result.error)) messageApi.error(result.error);
        return false;
      }
      appendEvent({ type: "approval_result", id, approved });
      return true;
    } finally {
      approvalInFlightRef.current.delete(key);
    }
  };

  const uploadFiles = async (task, selected) => {
    const names = [];
    const taskMission = missionIdentity(task);
    for (const file of selected) {
      const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = reject; reader.readAsDataURL(file); });
      const result = await api("/api/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: task.project, name: file.name, data, ...(taskMission ? { repositoryId: taskMission.repositoryId, taskCode: taskMission.taskCode, taskId: task.id } : {}) }) });
      if (result.error) messageApi.error(`${file.name}: ${result.error}`); else names.push(file.name);
    }
    setPendingFiles([]); return names;
  };

  const sendToTask = async (task, content, displayMessage = content, startTask = false, intent = "auto") => {
    // An explicit new request is a user action that should start at the latest
    // message even if the previous turn was left scrolled up.
    feedPinnedRef.current = true;
    setBusy(true); appendEvent({ type: "user", text: displayMessage });
    let response;
    try {
      response = await fetch(`/api/tasks/${task.id}/send`, { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin", body: JSON.stringify({ message: content, displayMessage, startTask, intent }) });
    } catch (error) { appendEvent({ type: "error", error: error.message }); setBusy(false); return; }
    if (!response.ok || !response.body) { appendEvent({ type: "error", error: `请求失败(${response.status})` }); setBusy(false); return; }
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    const consume = (chunk) => {
      buffer += decoder.decode(chunk, { stream: true });
      const packets = buffer.split("\n\n"); buffer = packets.pop() || "";
      packets.forEach((packet) => {
        const line = packet.split("\n").find((item) => item.startsWith("data: "));
        if (!line) return;
        try {
          const event = JSON.parse(line.slice(6));
          appendEvent(event);
          if (event.type === "approval_request" && autoApproveRef.current) approve(event.id, true, task);
          if (event.type === "done") setBusy(false);
        } catch { /* ignore malformed SSE packet */ }
      });
    };
    try { while (true) { const { value, done } = await reader.read(); if (done) break; consume(value); } if (buffer) consume(new Uint8Array()); } catch (error) { appendEvent({ type: "error", error: error.message }); }
    setBusy(false);
    const refreshedTasks = await loadTasks();
    const refreshed = refreshedTasks.find((item) => item.id === task.id);
    if (refreshed) setActive((previous) => previous && previous.id === refreshed.id ? { ...previous, ...refreshed } : previous);
    await loadFiles(task);
  };

  const send = async () => {
    if (busy) return;
    let task = active;
    const start = MISSION && !hasConversation && !text.trim();
    const userText = text.trim();
    if (!userText && !start) return;
    if (!task) task = await createTask();
    if (!task) return;
    const names = pendingFiles.length ? await uploadFiles(task, pendingFiles) : [];
    const messageText = start ? "请直接开始执行当前任务\n不需要等待我补充提示词。严格按照当前 execution-context 和系统规则完成全部工作。" : `${userText}${names.length ? `\n\n[用户上传了文件: ${names.join(", ")}]` : ""}`;
    const display = start ? "请直接开始执行当前任务" : userText;
    const intent = start ? "execute" : task.platformStatus === "COMPLETED" ? "chat" : "auto";
    setText(""); await sendToTask(task, messageText, display, start, intent);
  };

  const onAttach = () => {
    if (active?.platformStatus === "COMPLETED") {
      messageApi.info("任务已完成，请先点击“修改”再上传新的输入文件");
      return;
    }
    if (busy || active?.status === "working" || platformActionLoading) {
      messageApi.info("任务执行或状态变更期间不能修改输入文件");
      return;
    }
    fileInput.current?.click();
  };
  const onFilesSelected = (event) => { setPendingFiles(Array.from(event.target.files || [])); event.target.value = ""; };
  const onParams = async (patch) => { const result = await api("/api/params", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, params: result })); };
  const onModel = async (value) => { const result = await api("/api/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: value }) }); if (result.error) messageApi.error(result.error); else setMeta((previous) => ({ ...previous, model: result.model, provider: (previous.models || []).find((item) => item.id === result.model)?.provider || previous.provider })); };
  const onSaveKey = async () => { const result = await api("/api/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, key: keyValue }) }); if (result.error) messageApi.error(result.error); else messageApi.success("模型密钥已保存"); };

  const fileUrl = (path) => { const project = active?.project || ""; return `/p/${encodeURIComponent(project)}/${path.split("/").map(encodeURIComponent).join("/")}${missionSearch({ taskId: active?.id || "" }, active)}`; };
  const showPreview = (next) => {
    if (previewImageUrlRef.current) URL.revokeObjectURL(previewImageUrlRef.current);
    previewImageUrlRef.current = next?.image || "";
    setPreview(next);
  };
  const closePreview = () => {
    previewRequestRef.current += 1;
    showPreview(null);
  };
  const openFile = async (path) => {
    const requestId = ++previewRequestRef.current;
    setFilesOpen(true); setFocusFile(path);
    try {
      const response = await fetch(fileUrl(path), { credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const type = response.headers.get("content-type") || "";
      if (type.startsWith("image/")) {
        const blob = await response.blob();
        if (requestId !== previewRequestRef.current) return;
        showPreview({ path, image: URL.createObjectURL(blob) });
      } else if (/\.(xlsx?|xlsm)$/i.test(path)) {
        const [buffer, XLSX] = await Promise.all([response.arrayBuffer(), import("xlsx")]);
        if (requestId !== previewRequestRef.current) return;
        const workbook = XLSX.read(buffer, { type: "array", cellDates: true });
        const sheets = workbook.SheetNames.map((name) => ({ name, rows: XLSX.utils.sheet_to_json(workbook.Sheets[name], { header: 1, defval: "", raw: false }) }));
        showPreview({ path, xlsx: true, sheets });
      } else {
        const content = await response.text();
        if (requestId !== previewRequestRef.current) return;
        showPreview({ path, text: content, csv: /\.csv$/i.test(path) || type.includes("text/csv") });
      }
    } catch (error) {
      if (requestId === previewRequestRef.current) messageApi.error(`打开文件失败: ${error.message}`);
    }
  };
  const download = () => { if (!selectedFiles.length) return; const project = active?.project || ""; const query = new URLSearchParams({ project }); selectedFiles.forEach((path) => query.append("path", path)); const taskMission = missionIdentity(active); if (taskMission) { query.set("repositoryId", taskMission.repositoryId); query.set("taskCode", taskMission.taskCode); query.set("taskId", active?.id || ""); } window.open(`/api/download?${query}`, "_blank"); };
  const uploadToMinio = async () => {
    const taskMission = missionIdentity(active);
    if (!taskMission || !active || !selectedFiles.length) return;
    setMinioUploading(true);
    try {
      const result = await api("/api/minio/upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project: active.project, paths: selectedFiles, taskCode: taskMission.taskCode, repositoryId: taskMission.repositoryId, taskId: active.id, taskType: MISSION?.taskType || active.taskType || "" }) });
      if (result.error) { messageApi.error(result.error); return; }
      const failed = (result.results || []).filter((item) => !item.ok);
      if (result.uploaded) messageApi.success(`已上传 ${result.uploaded}/${result.total || selectedFiles.length} 个文件到 MinIO`);
      if (failed.length) messageApi.warning(failed.map((item) => `${item.name}: ${item.error}`).join("；"));
      if (result.task) {
        setActive(result.task);
        setTasks((previous) => previous.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
      }
      if (result.completionHint) messageApi.info(result.completionHint);
      else if (result.callback?.skipped) messageApi.info(`尚未完成：${result.callback.error}`);
      else if (result.callback) messageApi.warning(`结果已上传，但完成回写失败：${result.callback.error || "未知错误"}`);
      await loadFiles(active);
    } finally {
      setMinioUploading(false);
    }
  };

  const changePlatformStatus = async () => {
    if (!currentMission || !active || platformActionLoading) return;
    const completed = active.platformStatus === "COMPLETED";
    setPlatformActionLoading(true);
    try {
      const result = await api(`/api/tasks/${active.id}/platform-status`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: completed ? "edit" : "complete" }),
      });
      if (result.error) { messageApi.error(result.error); return; }
      if (result.task) {
        setActive(result.task);
        setTasks((previous) => previous.map((task) => task.id === result.task.id ? { ...task, ...result.task } : task));
      }
      messageApi.success(completed ? "已恢复为运行中，可继续修改并重新上传" : "已确认完成，结果已回写本体平台");
    } finally {
      setPlatformActionLoading(false);
    }
  };

  const toggleAutoApprove = () => {
    const next = !autoApprove;
    autoApproveRef.current = next;
    setAutoApprove(next);
    localStorage.setItem("oc_auto_approve", next ? "1" : "0");
    messageApi.success(next ? "已开启自动确认" : "已关闭自动确认");
    if (next) {
      const pending = events.find((event) => event.type === "approval_request");
      if (pending) void approve(pending.id, true, active);
    }
  };

  const sidebarTasks = tasks.filter((task) => !MISSION || (task.repositoryId === MISSION.repositoryId && task.taskCode === MISSION.taskCode));
  return <ConfigProvider theme={{ token: { colorPrimary: "#5f7f9d", borderRadius: 8, fontFamily: '"PingFang SC", -apple-system, sans-serif' } }}>
    {contextHolder}
    <div className="workbench">
      <aside className="sidebar">
        <div className="brand"><span className="brand-logo">硕</span><strong>硕磐智能</strong><Tag>Agent</Tag></div>
        <div className="sidebar-scroll">
          <Button className="new-task" onClick={handleNewSession}>+ 新会话</Button>
          <button className="section-toggle" onClick={() => setHistoryOpen((value) => !value)}><HistoryIcon />历史会话</button>
          {historyOpen && <div className="task-list">{sidebarTasks.length ? sidebarTasks.map((task) => <button className={`task-row ${active?.id === task.id ? "active" : ""}`} key={task.id} onClick={() => openTask(task)}><span>{task.title || "新会话"}</span><small><i className={task.status === "working" ? "working" : task.status === "error" ? "error" : ""} />{task.workspace || task.project} · {relativeTime(task.updated)}</small></button>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有会话" />}</div>}
          <Button className="settings-button" onClick={() => setSettingsOpen(true)}><ModelSettingsIcon /> 大语言模型设置</Button>
          {MISSION && <div className="current-mission">
            <Button type="text" className="current-mission-trigger" onClick={() => setMissionInfoOpen(true)}><CurrentMissionIcon /> 当前任务信息</Button>
            <small>{MISSION.taskCode} · 本体库 {MISSION.repositoryId}</small>
            <div className="sidebar-mission-info">
              {missionLoading ? <Spin size="small" /> : missionContext ? <RecursiveInfo value={missionContext} /> : <span className="sidebar-mission-empty">暂未获取到完整任务信息</span>}
            </div>
          </div>}
        </div>
        <div className="sandbox-note">沙箱模式：智能体只能操作当前任务工作目录。<br /><span>{meta.sandbox || "sandbox/"}</span></div>
      </aside>
      <main className="main-content">
        {view === "home" ? <section className="home-view"><h1>{MISSION ? (MISSION.taskType === "integration" ? "智能消歧与整合" : "智能建模") : "本体智能体"}</h1><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={false} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} /></section> : <section className="task-view">
          <header className="task-header"><i className={active?.status === "working" || busy ? "status-dot working" : "status-dot"} /><strong title={active?.title || "当前任务"}>{truncateTitle(active?.title || "当前任务")}</strong><Tag>{active?.workspace || active?.project}</Tag><span className="header-spacer" />{isMissionTask && active?.platformStatus !== "FAILED" && <Button type={active?.platformStatus === "COMPLETED" ? "default" : "primary"} icon={active?.platformStatus === "COMPLETED" ? <TaskEditIcon /> : <TaskCompleteIcon />} loading={platformActionLoading} disabled={busy || active?.status === "working" || minioUploading || (active?.platformStatus !== "COMPLETED" && active?.completionReady === false)} title={active?.platformStatus !== "COMPLETED" && active?.completionReady === false ? "请先上传全部任务结果" : ""} onClick={changePlatformStatus}>{active?.platformStatus === "COMPLETED" ? "修改" : "完成"}</Button>}<Button icon={<TaskFilesIcon />} onClick={() => { setFilesOpen(true); loadFiles(); }}>文件</Button></header>
          <div ref={feedRef} className="feed" onScroll={handleFeedScroll}><EventFeed events={events} onApprove={approve} files={files} onFile={openFile} busy={busy} /></div>
          <div className="task-composer"><Composer value={text} onChange={setText} onSend={send} onAttach={onAttach} pendingFiles={pendingFiles} mission={MISSION} busy={busy} hasConversation={hasConversation} model={model} models={meta.models} onModel={onModel} onOpenSettings={() => setSettingsOpen(true)} placeholder={placeholder} projects={meta.projects} project={selectedProject} onProject={setSelectedProject} autoApprove={autoApprove} onToggleAutoApprove={toggleAutoApprove} showAutoApprove={isMissionTask} /></div>
        </section>}
      </main>
      <FilePanel open={filesOpen} files={files} loading={filesLoading} selected={selectedFiles} focusPath={focusFile} resetKey={active?.id} onSelect={(path) => setSelectedFiles((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])} onSelectGroup={(paths) => setSelectedFiles((current) => paths.every((path) => current.includes(path)) ? current.filter((path) => !paths.includes(path)) : [...new Set([...current, ...paths])])} onOpen={openFile} onDownload={download} onUploadToMinio={uploadToMinio} uploadingToMinio={minioUploading} uploadBlocked={busy || active?.status === "working" || platformActionLoading} onClose={() => setFilesOpen(false)} onRefresh={() => loadFiles()} mission={isMissionTask} platformStatus={active?.platformStatus} />
      <input ref={fileInput} type="file" multiple hidden onChange={onFilesSelected} />
      {preview && <Modal open title={preview.path} footer={null} width="88vw" onCancel={closePreview}>{preview.image ? <img className="preview-image" src={preview.image} alt={preview.path} /> : preview.xlsx ? <SpreadsheetPreview sheets={preview.sheets} /> : preview.csv ? <CsvPreview text={preview.text} /> : <pre className="preview-text">{preview.text}</pre>}</Modal>}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} meta={meta} model={model} onModel={onModel} params={params} onParams={onParams} provider={provider} keyValue={keyValue} setKeyValue={setKeyValue} onSaveKey={onSaveKey} />
      {MISSION && <MissionInfo open={missionInfoOpen} context={missionContext} loading={missionLoading} onClose={() => setMissionInfoOpen(false)} />}
    </div>
  </ConfigProvider>;
}

createRoot(document.getElementById("root")).render(<AntApp><App /></AntApp>);
