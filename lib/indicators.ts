// Technical Indicators for Trading Strategies

export interface OHLC {
  open: number
  high: number
  low: number
  close: number
  epoch: number
}

// Simple Moving Average
export function SMA(prices: number[], period: number): number[] {
  const result: number[] = []
  for (let i = 0; i < prices.length; i++) {
    if (i < period - 1) {
      result.push(Number.NaN)
    } else {
      const sum = prices.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0)
      result.push(sum / period)
    }
  }
  return result
}

// Exponential Moving Average
export function EMA(prices: number[], period: number): number[] {
  const result: number[] = []
  const multiplier = 2 / (period + 1)

  // First EMA is SMA
  let ema = prices.slice(0, period).reduce((a, b) => a + b, 0) / period

  for (let i = 0; i < prices.length; i++) {
    if (i < period - 1) {
      result.push(Number.NaN)
    } else if (i === period - 1) {
      result.push(ema)
    } else {
      ema = (prices[i] - ema) * multiplier + ema
      result.push(ema)
    }
  }
  return result
}

// Relative Strength Index
export function RSI(prices: number[], period = 14): number[] {
  const result: number[] = []
  const gains: number[] = []
  const losses: number[] = []

  for (let i = 1; i < prices.length; i++) {
    const change = prices[i] - prices[i - 1]
    gains.push(change > 0 ? change : 0)
    losses.push(change < 0 ? Math.abs(change) : 0)
  }

  for (let i = 0; i < prices.length; i++) {
    if (i < period) {
      result.push(Number.NaN)
    } else {
      const avgGain = gains.slice(i - period, i).reduce((a, b) => a + b, 0) / period
      const avgLoss = losses.slice(i - period, i).reduce((a, b) => a + b, 0) / period

      if (avgLoss === 0) {
        result.push(100)
      } else {
        const rs = avgGain / avgLoss
        result.push(100 - 100 / (1 + rs))
      }
    }
  }
  return result
}

// MACD
export function MACD(
  prices: number[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9,
): {
  macd: number[]
  signal: number[]
  histogram: number[]
} {
  const fastEMA = EMA(prices, fastPeriod)
  const slowEMA = EMA(prices, slowPeriod)

  const macdLine: number[] = []
  for (let i = 0; i < prices.length; i++) {
    if (isNaN(fastEMA[i]) || isNaN(slowEMA[i])) {
      macdLine.push(Number.NaN)
    } else {
      macdLine.push(fastEMA[i] - slowEMA[i])
    }
  }

  const validMacd = macdLine.filter((v) => !isNaN(v))
  const signalLine = EMA(validMacd, signalPeriod)

  // Align signal line with macd
  const fullSignal: number[] = []
  let signalIndex = 0
  for (let i = 0; i < macdLine.length; i++) {
    if (isNaN(macdLine[i])) {
      fullSignal.push(Number.NaN)
    } else {
      fullSignal.push(signalLine[signalIndex] || Number.NaN)
      signalIndex++
    }
  }

  const histogram: number[] = macdLine.map((m, i) =>
    isNaN(m) || isNaN(fullSignal[i]) ? Number.NaN : m - fullSignal[i],
  )

  return { macd: macdLine, signal: fullSignal, histogram }
}

// Stochastic Oscillator
export function Stochastic(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14,
): {
  k: number[]
  d: number[]
} {
  const kValues: number[] = []

  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) {
      kValues.push(Number.NaN)
    } else {
      const highestHigh = Math.max(...highs.slice(i - period + 1, i + 1))
      const lowestLow = Math.min(...lows.slice(i - period + 1, i + 1))
      const k = ((closes[i] - lowestLow) / (highestHigh - lowestLow)) * 100
      kValues.push(k)
    }
  }

  const dValues = SMA(
    kValues.filter((v) => !isNaN(v)),
    3,
  )

  // Align D with K
  const fullD: number[] = []
  let dIndex = 0
  for (let i = 0; i < kValues.length; i++) {
    if (isNaN(kValues[i])) {
      fullD.push(Number.NaN)
    } else {
      fullD.push(dValues[dIndex] || Number.NaN)
      dIndex++
    }
  }

  return { k: kValues, d: fullD }
}

// Bollinger Bands
export function BollingerBands(
  prices: number[],
  period = 20,
  stdDev = 2,
): {
  upper: number[]
  middle: number[]
  lower: number[]
} {
  const middle = SMA(prices, period)
  const upper: number[] = []
  const lower: number[] = []

  for (let i = 0; i < prices.length; i++) {
    if (isNaN(middle[i])) {
      upper.push(Number.NaN)
      lower.push(Number.NaN)
    } else {
      const slice = prices.slice(Math.max(0, i - period + 1), i + 1)
      const mean = middle[i]
      const variance = slice.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / slice.length
      const std = Math.sqrt(variance)
      upper.push(mean + stdDev * std)
      lower.push(mean - stdDev * std)
    }
  }

  return { upper, middle, lower }
}

// ADX (Average Directional Index)
export function ADX(highs: number[], lows: number[], closes: number[], period = 14): number[] {
  const result: number[] = []
  const trueRanges: number[] = []
  const plusDM: number[] = []
  const minusDM: number[] = []

  for (let i = 1; i < closes.length; i++) {
    const high = highs[i]
    const low = lows[i]
    const prevHigh = highs[i - 1]
    const prevLow = lows[i - 1]
    const prevClose = closes[i - 1]

    const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose))
    trueRanges.push(tr)

    const upMove = high - prevHigh
    const downMove = prevLow - low

    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0)
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0)
  }

  // Calculate smoothed values
  const smoothedTR = EMA(trueRanges, period)
  const smoothedPlusDM = EMA(plusDM, period)
  const smoothedMinusDM = EMA(minusDM, period)

  const dx: number[] = []
  for (let i = 0; i < smoothedTR.length; i++) {
    if (isNaN(smoothedTR[i]) || smoothedTR[i] === 0) {
      dx.push(Number.NaN)
    } else {
      const plusDI = (smoothedPlusDM[i] / smoothedTR[i]) * 100
      const minusDI = (smoothedMinusDM[i] / smoothedTR[i]) * 100
      const sum = plusDI + minusDI
      dx.push(sum === 0 ? 0 : (Math.abs(plusDI - minusDI) / sum) * 100)
    }
  }

  const adx = EMA(
    dx.filter((v) => !isNaN(v)),
    period,
  )

  // Align ADX with original length
  for (let i = 0; i < closes.length; i++) {
    if (i < period * 2) {
      result.push(Number.NaN)
    } else {
      result.push(adx[i - period * 2] || Number.NaN)
    }
  }

  return result
}

// Get last digit from price
export function getLastDigit(price: number): number {
  const priceStr = price.toString()
  return Number.parseInt(priceStr[priceStr.length - 1])
}

// Calculate digit frequency
export function digitFrequency(prices: number[]): Map<number, number> {
  const freq = new Map<number, number>()
  for (let i = 0; i <= 9; i++) {
    freq.set(i, 0)
  }

  for (const price of prices) {
    const digit = getLastDigit(price)
    freq.set(digit, (freq.get(digit) || 0) + 1)
  }

  return freq
}

// Analyze tick patterns
export function analyzeTickPattern(prices: number[]): {
  trend: "up" | "down" | "sideways"
  strength: number
  consecutive: number
  pattern: string
} {
  if (prices.length < 5) {
    return { trend: "sideways", strength: 0, consecutive: 0, pattern: "insufficient" }
  }

  let ups = 0
  let downs = 0
  let consecutive = 0
  let lastDirection = 0

  for (let i = 1; i < prices.length; i++) {
    const diff = prices[i] - prices[i - 1]
    if (diff > 0) {
      ups++
      if (lastDirection === 1) {
        consecutive++
      } else {
        consecutive = 1
        lastDirection = 1
      }
    } else if (diff < 0) {
      downs++
      if (lastDirection === -1) {
        consecutive++
      } else {
        consecutive = 1
        lastDirection = -1
      }
    }
  }

  const total = ups + downs
  const ratio = total > 0 ? ups / total : 0.5

  let trend: "up" | "down" | "sideways"
  let pattern: string

  if (ratio > 0.6) {
    trend = "up"
    pattern = "bullish"
  } else if (ratio < 0.4) {
    trend = "down"
    pattern = "bearish"
  } else {
    trend = "sideways"
    pattern = "ranging"
  }

  const strength = Math.abs(ratio - 0.5) * 2 * 100

  return { trend, strength, consecutive, pattern }
}
