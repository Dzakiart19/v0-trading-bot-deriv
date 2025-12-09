"use client"

import { useEffect, useRef, useState } from "react"

interface TickData {
  quote: number
  epoch: number
}

interface TradingChartProps {
  ticks: TickData[]
  height?: number
  showGrid?: boolean
  lineColor?: string
}

export function TradingChart({ ticks, height = 300, showGrid = true, lineColor = "#22c55e" }: TradingChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 600, height })

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height,
        })
      }
    }

    updateDimensions()
    window.addEventListener("resize", updateDimensions)
    return () => window.removeEventListener("resize", updateDimensions)
  }, [height])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || ticks.length < 2) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const { width, height } = dimensions
    const padding = { top: 20, right: 60, bottom: 30, left: 10 }
    const chartWidth = width - padding.left - padding.right
    const chartHeight = height - padding.top - padding.bottom

    // Clear canvas
    ctx.fillStyle = "#0a0a0a"
    ctx.fillRect(0, 0, width, height)

    // Get price range
    const prices = ticks.map((t) => t.quote)
    const minPrice = Math.min(...prices)
    const maxPrice = Math.max(...prices)
    const priceRange = maxPrice - minPrice || 1
    const pricePadding = priceRange * 0.1

    // Draw grid
    if (showGrid) {
      ctx.strokeStyle = "#1f1f1f"
      ctx.lineWidth = 1

      // Horizontal lines
      for (let i = 0; i <= 5; i++) {
        const y = padding.top + (chartHeight / 5) * i
        ctx.beginPath()
        ctx.moveTo(padding.left, y)
        ctx.lineTo(width - padding.right, y)
        ctx.stroke()

        // Price labels
        const price = maxPrice + pricePadding - ((priceRange + pricePadding * 2) / 5) * i
        ctx.fillStyle = "#666"
        ctx.font = "10px sans-serif"
        ctx.textAlign = "left"
        ctx.fillText(price.toFixed(5), width - padding.right + 5, y + 3)
      }
    }

    // Draw line chart
    ctx.strokeStyle = lineColor
    ctx.lineWidth = 2
    ctx.beginPath()

    ticks.forEach((tick, i) => {
      const x = padding.left + (chartWidth / (ticks.length - 1)) * i
      const y =
        padding.top +
        chartHeight -
        ((tick.quote - minPrice + pricePadding) / (priceRange + pricePadding * 2)) * chartHeight

      if (i === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    })
    ctx.stroke()

    // Draw gradient fill
    const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom)
    gradient.addColorStop(0, `${lineColor}40`)
    gradient.addColorStop(1, `${lineColor}00`)

    ctx.fillStyle = gradient
    ctx.beginPath()
    ticks.forEach((tick, i) => {
      const x = padding.left + (chartWidth / (ticks.length - 1)) * i
      const y =
        padding.top +
        chartHeight -
        ((tick.quote - minPrice + pricePadding) / (priceRange + pricePadding * 2)) * chartHeight

      if (i === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    })
    ctx.lineTo(padding.left + chartWidth, height - padding.bottom)
    ctx.lineTo(padding.left, height - padding.bottom)
    ctx.closePath()
    ctx.fill()

    // Draw current price indicator
    if (ticks.length > 0) {
      const lastTick = ticks[ticks.length - 1]
      const lastX = width - padding.right
      const lastY =
        padding.top +
        chartHeight -
        ((lastTick.quote - minPrice + pricePadding) / (priceRange + pricePadding * 2)) * chartHeight

      // Dot
      ctx.beginPath()
      ctx.arc(lastX, lastY, 5, 0, Math.PI * 2)
      ctx.fillStyle = lineColor
      ctx.fill()

      // Price box
      ctx.fillStyle = lineColor
      ctx.fillRect(lastX + 5, lastY - 10, 55, 20)
      ctx.fillStyle = "#000"
      ctx.font = "bold 11px sans-serif"
      ctx.textAlign = "left"
      ctx.fillText(lastTick.quote.toFixed(5), lastX + 8, lastY + 4)
    }
  }, [ticks, dimensions, showGrid, lineColor])

  return (
    <div ref={containerRef} className="w-full">
      <canvas ref={canvasRef} width={dimensions.width} height={dimensions.height} className="rounded-lg" />
    </div>
  )
}
