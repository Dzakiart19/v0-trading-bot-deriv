"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Slider } from "@/components/ui/slider"
import { TradingChart } from "@/components/trading-chart"
import { type DerivAPI, type TickData, createDerivAPI } from "@/lib/deriv-api"
import { RSI, EMA, MACD, BollingerBands, analyzeTickPattern } from "@/lib/indicators"
import {
  ArrowLeft,
  Wifi,
  WifiOff,
  Target,
  ArrowUp,
  ArrowDown,
  Play,
  Square,
  AlertTriangle,
  CheckCircle2,
  Clock,
} from "lucide-react"

const SYMBOLS = [
  { value: "R_10", label: "Volatility 10" },
  { value: "R_25", label: "Volatility 25" },
  { value: "R_50", label: "Volatility 50" },
  { value: "R_75", label: "Volatility 75" },
  { value: "R_100", label: "Volatility 100" },
]

interface Signal {
  type: "rise" | "fall"
  confidence: number
  indicators: string[]
  timestamp: Date
  status: "waiting" | "ready" | "expired"
}

export default function SniperPage() {
  const router = useRouter()
  const [api, setApi] = useState<DerivAPI | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [symbol, setSymbol] = useState("R_100")
  const [ticks, setTicks] = useState<TickData[]>([])
  const [balance, setBalance] = useState(0)
  const [currency, setCurrency] = useState("USD")
  const [totalProfit, setTotalProfit] = useState(0)

  const [stake, setStake] = useState(5)
  const [minConfidence, setMinConfidence] = useState(85)
  const [isAutoRunning, setIsAutoRunning] = useState(false)

  // Sniper signals
  const [currentSignal, setCurrentSignal] = useState<Signal | null>(null)
  const [signalHistory, setSignalHistory] = useState<Signal[]>([])
  const [waitingForSignal, setWaitingForSignal] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem("deriv_token")
    if (!token) {
      router.push("/")
      return
    }

    const derivApi = createDerivAPI(token)
    derivApi
      .connect()
      .then(() => {
        setApi(derivApi)
        setIsConnected(true)

        derivApi.getBalance().then(({ balance, currency }) => {
          setBalance(balance)
          setCurrency(currency)
        })

        derivApi.getTickHistory(symbol, 100).then(setTicks)
        derivApi.subscribeTicks(symbol, (tick) => {
          setTicks((prev) => [...prev.slice(-99), tick])
        })
      })
      .catch(() => {
        router.push("/")
      })

    return () => {
      derivApi.disconnect()
    }
  }, [router])

  useEffect(() => {
    if (!api || !isConnected) return

    api.unsubscribeTicks(symbol).then(() => {
      api.getTickHistory(symbol, 100).then(setTicks)
      api.subscribeTicks(symbol, (tick) => {
        setTicks((prev) => [...prev.slice(-99), tick])
      })
    })
  }, [symbol, api, isConnected])

  // Sniper analysis - only trigger when high confidence
  useEffect(() => {
    if (ticks.length < 50) return

    const prices = ticks.map((t) => t.quote)

    // Multi-indicator analysis
    const rsiValues = RSI(prices, 14)
    const ema9 = EMA(prices, 9)
    const ema21 = EMA(prices, 21)
    const macdResult = MACD(prices)
    const bb = BollingerBands(prices, 20, 2)
    const pattern = analyzeTickPattern(prices.slice(-20))

    const currentRSI = rsiValues[rsiValues.length - 1]
    const currentEMA9 = ema9[ema9.length - 1]
    const currentEMA21 = ema21[ema21.length - 1]
    const currentMACD = macdResult.histogram[macdResult.histogram.length - 1]
    const currentPrice = prices[prices.length - 1]
    const upperBB = bb.upper[bb.upper.length - 1]
    const lowerBB = bb.lower[bb.lower.length - 1]

    // Count strong signals
    const indicators: string[] = []
    let bullishScore = 0
    let bearishScore = 0

    // RSI extreme
    if (currentRSI < 25) {
      bullishScore += 25
      indicators.push("RSI Oversold")
    } else if (currentRSI > 75) {
      bearishScore += 25
      indicators.push("RSI Overbought")
    }

    // EMA crossover
    if (currentEMA9 > currentEMA21 * 1.001) {
      bullishScore += 20
      indicators.push("EMA Bullish Cross")
    } else if (currentEMA9 < currentEMA21 * 0.999) {
      bearishScore += 20
      indicators.push("EMA Bearish Cross")
    }

    // MACD
    if (currentMACD > 0.0001) {
      bullishScore += 15
      indicators.push("MACD Positive")
    } else if (currentMACD < -0.0001) {
      bearishScore += 15
      indicators.push("MACD Negative")
    }

    // Bollinger Bands
    if (currentPrice <= lowerBB) {
      bullishScore += 25
      indicators.push("BB Lower Touch")
    } else if (currentPrice >= upperBB) {
      bearishScore += 25
      indicators.push("BB Upper Touch")
    }

    // Trend strength
    if (pattern.trend === "down" && pattern.consecutive >= 5) {
      bullishScore += 15
      indicators.push("Reversal Expected")
    } else if (pattern.trend === "up" && pattern.consecutive >= 5) {
      bearishScore += 15
      indicators.push("Reversal Expected")
    }

    const maxScore = Math.max(bullishScore, bearishScore)
    const confidence = Math.min(maxScore, 95)

    // Only create signal if confidence meets threshold
    if (confidence >= minConfidence && waitingForSignal) {
      const signal: Signal = {
        type: bullishScore > bearishScore ? "rise" : "fall",
        confidence,
        indicators,
        timestamp: new Date(),
        status: "ready",
      }

      setCurrentSignal(signal)
      setSignalHistory((prev) => [signal, ...prev.slice(0, 9)])
      setWaitingForSignal(false)
    }
  }, [ticks, minConfidence, waitingForSignal])

  const handleTrade = async (type: "rise" | "fall") => {
    if (!api) return

    try {
      const proposal = await api.getProposal({
        contract_type: type === "rise" ? "CALL" : "PUT",
        symbol,
        duration: 5,
        duration_unit: "t",
        amount: stake,
        basis: "stake",
      })

      const result = await api.buyContract(proposal.id, proposal.ask_price)

      const { balance: newBalance } = await api.getBalance()
      setBalance(newBalance)

      // Clear signal after trade
      setCurrentSignal(null)

      const checkResult = setInterval(async () => {
        const update = await api.getContractUpdate(result.contract_id)
        if (update.status !== "open") {
          clearInterval(checkResult)
          setTotalProfit((prev) => prev + update.profit)
          const { balance: finalBalance } = await api.getBalance()
          setBalance(finalBalance)
        }
      }, 1000)
    } catch (error) {
      console.error("Trade error:", error)
    }
  }

  const startSniping = () => {
    setWaitingForSignal(true)
    setCurrentSignal(null)
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-lg font-bold">Sniper Strategy</h1>
              <p className="text-xs text-muted-foreground">High Probability Only ({minConfidence}%+)</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              {isConnected ? <Wifi className="h-4 w-4 text-green-500" /> : <WifiOff className="h-4 w-4 text-red-500" />}
            </div>
            <div className="text-right">
              <div className="font-semibold">
                {balance.toFixed(2)} {currency}
              </div>
              <div className={`text-xs ${totalProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                {totalProfit >= 0 ? "+" : ""}
                {totalProfit.toFixed(2)}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            {/* Symbol & Price */}
            <div className="flex items-center gap-4">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[200px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SYMBOLS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {ticks.length > 0 && (
                <span className="text-2xl font-mono font-bold">{ticks[ticks.length - 1]?.quote.toFixed(5)}</span>
              )}
            </div>

            {/* Chart */}
            <Card>
              <CardContent className="p-4">
                <TradingChart
                  ticks={ticks}
                  height={300}
                  lineColor={
                    currentSignal?.type === "rise" ? "#22c55e" : currentSignal?.type === "fall" ? "#ef4444" : "#6b7280"
                  }
                />
              </CardContent>
            </Card>

            {/* Signal Status */}
            <Card
              className={`border-2 ${
                currentSignal?.status === "ready"
                  ? "border-green-500 bg-green-500/5"
                  : waitingForSignal
                    ? "border-yellow-500 bg-yellow-500/5"
                    : "border-muted"
              }`}
            >
              <CardContent className="py-6">
                {currentSignal?.status === "ready" ? (
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <CheckCircle2 className="h-12 w-12 text-green-500" />
                      <div>
                        <div className="text-sm text-muted-foreground">Signal Ready</div>
                        <div className="text-2xl font-bold flex items-center gap-2">
                          {currentSignal.type === "rise" ? (
                            <ArrowUp className="h-6 w-6 text-green-500" />
                          ) : (
                            <ArrowDown className="h-6 w-6 text-red-500" />
                          )}
                          {currentSignal.type.toUpperCase()}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm text-muted-foreground">Confidence</div>
                      <div className="text-3xl font-bold text-green-500">{currentSignal.confidence}%</div>
                    </div>
                  </div>
                ) : waitingForSignal ? (
                  <div className="flex items-center justify-center gap-4">
                    <Clock className="h-10 w-10 text-yellow-500 animate-pulse" />
                    <div className="text-center">
                      <div className="text-lg font-semibold">Waiting for High Probability Signal...</div>
                      <div className="text-sm text-muted-foreground">Minimum confidence: {minConfidence}%</div>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-center gap-4">
                    <Target className="h-10 w-10 text-muted-foreground" />
                    <div className="text-center">
                      <div className="text-lg font-semibold">Sniper Mode Ready</div>
                      <div className="text-sm text-muted-foreground">Click "Start Sniping" to begin</div>
                    </div>
                  </div>
                )}

                {/* Signal Indicators */}
                {currentSignal && currentSignal.indicators.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {currentSignal.indicators.map((ind, i) => (
                      <Badge key={i} variant="secondary">
                        {ind}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Signal History */}
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Recent Signals</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {signalHistory.length === 0 ? (
                    <p className="text-center text-muted-foreground py-4">No signals yet</p>
                  ) : (
                    signalHistory.map((signal, i) => (
                      <div key={i} className="flex items-center justify-between p-2 bg-muted/30 rounded">
                        <div className="flex items-center gap-2">
                          {signal.type === "rise" ? (
                            <ArrowUp className="h-4 w-4 text-green-500" />
                          ) : (
                            <ArrowDown className="h-4 w-4 text-red-500" />
                          )}
                          <span className="font-medium">{signal.type.toUpperCase()}</span>
                        </div>
                        <Badge>{signal.confidence}%</Badge>
                        <span className="text-xs text-muted-foreground">{signal.timestamp.toLocaleTimeString()}</span>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Trade Panel */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="py-3">
                <CardTitle className="text-lg flex items-center gap-2">
                  <Target className="h-5 w-5 text-red-500" />
                  Sniper Config
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Stake */}
                <div className="space-y-2">
                  <Label>Stake ({currency})</Label>
                  <Input
                    type="number"
                    value={stake}
                    onChange={(e) => setStake(Number.parseFloat(e.target.value) || 0)}
                    min={0.35}
                    step={0.1}
                  />
                </div>

                {/* Quick Stakes */}
                <div className="flex gap-2">
                  {[5, 10, 25, 50].map((val) => (
                    <Button
                      key={val}
                      variant={stake === val ? "default" : "outline"}
                      size="sm"
                      className="flex-1"
                      onClick={() => setStake(val)}
                    >
                      ${val}
                    </Button>
                  ))}
                </div>

                {/* Min Confidence */}
                <div className="space-y-2">
                  <Label className="flex items-center justify-between">
                    <span>Min Confidence</span>
                    <span className="text-primary font-semibold">{minConfidence}%</span>
                  </Label>
                  <Slider
                    value={[minConfidence]}
                    onValueChange={([v]) => setMinConfidence(v)}
                    min={70}
                    max={95}
                    step={5}
                  />
                </div>

                {/* Warning */}
                <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                    <div className="text-sm">
                      <p className="font-medium text-yellow-500">Sniper Mode</p>
                      <p className="text-muted-foreground">
                        Only trades when confidence reaches {minConfidence}%+. May wait several minutes between signals.
                      </p>
                    </div>
                  </div>
                </div>

                {/* Start Sniping Button */}
                {!currentSignal && (
                  <Button
                    size="lg"
                    className={`w-full h-14 ${waitingForSignal ? "bg-yellow-600 hover:bg-yellow-700" : "bg-red-600 hover:bg-red-700"}`}
                    onClick={startSniping}
                    disabled={waitingForSignal}
                  >
                    {waitingForSignal ? (
                      <>
                        <Clock className="h-5 w-5 mr-2 animate-spin" />
                        SEARCHING...
                      </>
                    ) : (
                      <>
                        <Target className="h-5 w-5 mr-2" />
                        START SNIPING
                      </>
                    )}
                  </Button>
                )}

                {/* Trade Buttons when signal ready */}
                {currentSignal?.status === "ready" && (
                  <div className="space-y-3">
                    <Button
                      size="lg"
                      className={`w-full h-14 ${currentSignal.type === "rise" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"}`}
                      onClick={() => handleTrade(currentSignal.type)}
                    >
                      {currentSignal.type === "rise" ? (
                        <>
                          <ArrowUp className="h-5 w-5 mr-2" />
                          EXECUTE RISE
                        </>
                      ) : (
                        <>
                          <ArrowDown className="h-5 w-5 mr-2" />
                          EXECUTE FALL
                        </>
                      )}
                    </Button>
                    <Button variant="outline" className="w-full bg-transparent" onClick={() => setCurrentSignal(null)}>
                      Skip Signal
                    </Button>
                  </div>
                )}

                {/* Auto Mode */}
                <Button
                  size="lg"
                  className={`w-full h-12 ${isAutoRunning ? "bg-orange-600 hover:bg-orange-700" : "bg-blue-600 hover:bg-blue-700"}`}
                  onClick={() => setIsAutoRunning(!isAutoRunning)}
                >
                  {isAutoRunning ? (
                    <>
                      <Square className="h-5 w-5 mr-2" />
                      STOP AUTO
                    </>
                  ) : (
                    <>
                      <Play className="h-5 w-5 mr-2" />
                      AUTO EXECUTE
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
