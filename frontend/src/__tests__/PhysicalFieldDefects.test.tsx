/// <reference types="vitest/globals" />
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import BigScreenPage from '../pages/BigScreenPage'

afterEach(cleanup)

describe('Day6 physical field defects', () => {
  it('DF-002: big screen headings use unrestricted overflow wrapping', () => {
    render(
      <MemoryRouter initialEntries={['/bigscreen?tid=12']}>
        <BigScreenPage tid={12} />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy()
    const css = readFileSync(join(process.cwd(), 'src', 'index.css'), 'utf8')
    const headingRule = /\.bigscreen-header h1\s*\{[\s\S]*?\}/.exec(css)?.[0] ?? ''
    expect(headingRule).toContain('overflow-wrap: anywhere')
  })
})
