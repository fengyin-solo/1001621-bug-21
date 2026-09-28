<template>
  <section class="page" data-module="bridge">
    <header class="page-head">
      <div>
        <h2>廊桥对接管理</h2>
        <p class="page-desc">维护对接任务，围绕对接单号、关联航班、廊桥编号、对接时刻做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记对接任务</button>
        <button class="btn" type="button" :disabled="exporting" @click="exportRows">
          {{ exporting ? '正在导出…' : '导出廊桥对接清单' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>数据异常</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span v-if="row['数据异常']" class="error-text">{{ row['数据异常'] }}</span>
            <span v-else class="ok-text">正常</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无廊桥对接数据，可先登记对接任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条廊桥对接记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/bridge'
const columns = ["对接单号", "关联航班", "廊桥编号", "对接时刻", "撤桥时刻", "操作人员", "对接结果", "对接状态"]
const actions = ["开始对接", "确认撤离", "取消对接"]
const statuses = ["待对接", "对接中", "已撤离", "已取消"]
const stats = [{"label": "待对接任务", "value": 0}, {"label": "对接中任务", "value": 0}, {"label": "本月对接次数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const exporting = ref(false)
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function activeQuery() {
  // 只带上有值的筛选条件，列表和导出共用同一份查询串，保证条数对得上
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = (filters.value[field] ?? '').trim()
    if (value) {
      params.set(field, value)
    }
  }
  return params.toString()
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function toCsv(data: Row[], headers: string[]): string {
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? '' : String(value)
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const lines = [headers.map(escape).join(',')]
  for (const row of data) {
    lines.push(headers.map((header) => escape(row[header] ?? '')).join(','))
  }
  // 加 BOM，Excel 打开中文不乱码
  return '﻿' + lines.join('\r\n')
}

async function exportRows() {
  errorMessage.value = ''
  exporting.value = true
  try {
    const query = activeQuery()
    const response = await request(`${ENDPOINT}/export${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error(`导出失败（接口返回 ${response.status}），文件未生成`)
    }
    const payload = await response.json()
    const items: Row[] = payload.items ?? []
    if (payload.total !== items.length) {
      throw new Error(`导出条数与清单不一致（清单 ${payload.total} 条，实际导出 ${items.length} 条），请重试`)
    }
    const headers = [...columns, '数据异常']
    const blob = new Blob([toCsv(items, headers)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `廊桥对接清单_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '廊桥对接清单导出失败'
  } finally {
    exporting.value = false
  }
}

function openCreate() {
  errorMessage.value = '对接任务登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('廊桥对接动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (payload && payload.ok === false) {
      throw new Error(payload.message || '廊桥对接动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '廊桥对接操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = activeQuery()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error('对接任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '廊桥对接列表读取失败'
  }
}

onMounted(reload)
</script>
