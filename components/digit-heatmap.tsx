"use client"

import { useMemo } from "react"

interface DigitHeatmapProps {
  prices: number[]
  onDigitClick?: (digit: number) => void
  selectedDigits?: number[]
}

export function DigitHeatmap({ prices, onDigitClick, selectedDigits = [] }: DigitHeatmapProps) {
  const digitData = useMemo(() => {
    const freq = new Map<number, number>()
    for (let i = 0; i <= 9; i++) {
      freq.set(i, 0)
    }

    for (const price of prices) {
      const priceStr = price.toString()
      const digit = Number.parseInt(priceStr[priceStr.length - 1])
      freq.set(digit, (freq.get(digit) || 0) + 1)
    }

    const total = prices.length || 1
    const result: Array<{ digit: number; count: number; percentage: number; isHot: boolean; isCold: boolean }> = []

    const counts = Array.from(freq.values())
    const maxCount = Math.max(...counts)
    const minCount = Math.min(...counts)
    const threshold = total / 10 // Expected frequency

    for (let i = 0; i <= 9; i++) {
      const count = freq.get(i) || 0
      const percentage = (count / total) * 100
      result.push({
        digit: i,
        count,
        percentage,
        isHot: count >= maxCount * 0.9,
        isCold: count <= minCount * 1.1,
      })
    }

    return result
  }, [prices])

  const getColor = (percentage: number, isHot: boolean, isCold: boolean) => {
    if (isHot) return "bg-red-500 text-white"
    if (isCold) return "bg-blue-500 text-white"
    if (percentage > 12) return "bg-orange-400 text-black"
    if (percentage < 8) return "bg-cyan-400 text-black"
    return "bg-gray-600 text-white"
  }

  return (
    <div className="grid grid-cols-5 gap-2">
      {digitData.map(({ digit, count, percentage, isHot, isCold }) => {
        const isSelected = selectedDigits.includes(digit)
        return (
          <button
            key={digit}
            onClick={() => onDigitClick?.(digit)}
            className={`
              relative p-4 rounded-lg transition-all
              ${getColor(percentage, isHot, isCold)}
              ${isSelected ? "ring-2 ring-white ring-offset-2 ring-offset-background" : ""}
              hover:scale-105 hover:shadow-lg
            `}
          >
            <div className="text-2xl font-bold">{digit}</div>
            <div className="text-xs opacity-80">{percentage.toFixed(1)}%</div>
            <div className="text-xs opacity-60">{count}x</div>
            {isHot && <span className="absolute top-1 right-1 text-xs">🔥</span>}
            {isCold && <span className="absolute top-1 right-1 text-xs">❄️</span>}
          </button>
        )
      })}
    </div>
  )
}
