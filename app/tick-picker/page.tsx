"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { TradingChart } from "@/components/trading-chart"
import { type DerivAPI, type TickData, createDerivAPI } from "@/lib/deriv-api"
import { analyzeTickPattern } from "@/lib/indicators"
import {
  ArrowLeft,
  Wifi,
  WifiOff,
  ArrowUp,
  ArrowDown,
  Play,
  Square,
  TrendingUp,
  TrendingDown,
  Minus,
  Settings2,
} from "lucide-react"

const SYMBOLS = [
  { value: "R_10", label: "Volatility 10" },
  { value: "R_25", label: "Volatility 25" },
  { value: "R_50", label: "Volatility 50" },
  { value: "R_75", label: "Volatility 75" },
  { value: "R_100", label: "Volatility 100" },
  { value: "1HZ10V", label: "Volatility 10 (1s)" },
  { value: "1HZ100V", label: "Volatility 100 (1s)" },
]

interface TradeHistory {
  id: number
  type: string
  amount: number
  profit: number
  status: "won" | "lost" | "open"
}

export default function TickPickerPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [api, setApi] = useState<DerivAPI | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [symbol, setSymbol] = useState("R_100")
  const [ticks, setTicks] = useState<TickData[]>([])
  const [balance, setBalance] = useState(0)
  const [currency, setCurrency] = useState("USD")
  const [totalProfit, setTotalProfit] = useState(0)
  const [winRate, setWinRate] = useState(0)
  const [trades, setTrades] = useState<TradeHistory[]>([])

  // Auto trading state
  const [isAutoRunning, setIsAutoRunning] = useState(false)
  const [isTrading, setIsTrading] = useState(false)
  const [stake, setStake] = useState(1)
  const [duration, setDuration] = useState(5)
  const [martingale, setMartingale] = useState(true)
  const [martingaleLevel, setMartingaleLevel] = useState(0)
  const [targetProfit, setTargetProfit] = useState(10)
  const [stopLoss, setStopLoss] = useState(20)
  const [showSettings, setShowSettings] = useState(false)

  // Pattern analysis
  const [pattern, setPattern] = useState<{
    trend: "up" | "down" | "sideways"
    strength: number
    consecutive: number
    prediction: "rise" | "fall"
    confidence: number
  } | null>(null)

  // Refs for async callbacks
  const autoRunningRef = useRef(false)
  const martingaleLevelRef = useRef(0)
  const totalProfitRef = useRef(0)

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

        // Auto start if param is set
        if (searchParams.get("auto") === "true") {
          setTimeout(() => {
            setIsAutoRunning(true)
            autoRunningRef.current = true
          }, 2000)
        }
      })
      .catch(() => {
        router.push("/")
      })

    return () => {
      derivApi.disconnect()
    }
  }, [router, searchParams])

  useEffect(() => {
    if (!api || !isConnected) return

    api.unsubscribeTicks(symbol).then(() => {
      api.getTickHistory(symbol, 100).then(setTicks)
      api.subscribeTicks(symbol, (tick) => {
        setTicks((prev) => [...prev.slice(-99), tick])
      })
    })
  }, [symbol, api, isConnected])

  // Analyze ticks and auto trade
  useEffect(() => {
    if (ticks.length < 20) return

    const prices = ticks.map((t) => t.quote)
    const analysis = analyzeTickPattern(prices.slice(-30))

    const recent = prices.slice(-10)
    let rises = 0
    let falls = 0

    for (let i = 1; i < recent.length; i++) {
      if (recent[i] > recent[i - 1]) rises++
      else if (recent[i] < recent[i - 1]) falls++
    }

    let prediction: "rise" | "fall"
    let confidence: number

    if (analysis.consecutive >= 5) {
      prediction = analysis.trend === "up" ? "fall" : "rise"
      confidence = Math.min(70 + analysis.consecutive * 2, 85)
    } else {
      prediction = rises > falls ? "rise" : "fall"
      confidence = Math.min(50 + Math.abs(rises - falls) * 5, 80)
    }

    const newPattern = {
      trend: analysis.trend as "up" | "down" | "sideways",
      strength: analysis.strength,
      consecutive: analysis.consecutive,
      prediction,
      confidence,
    }

    setPattern(newPattern)

    // Auto execute trade when confidence is high enough
    if (autoRunningRef.current && !isTrading && confidence >= 65) {
      executeTrade(prediction)
    }
  }, [ticks])

  const executeTrade = useCallback(
    async (direction: "rise" | "fall") => {
      if (!api || isTrading) return

      // Check limits
      if (totalProfitRef.current >= targetProfit || totalProfitRef.current <= -stopLoss) {
        setIsAutoRunning(false)
        autoRunningRef.current = false
        return
      }

      setIsTrading(true)

      try {
        let currentStake = stake
        if (martingale && martingaleLevelRef.current > 0) {
          currentStake = stake * Math.pow(2, martingaleLevelRef.current)
        }
        currentStake = Math.min(currentStake, balance * 0.2)

        const proposal = await api.getProposal({
          contract_type: direction === "rise" ? "CALL" : "PUT",
          symbol,
          duration,
          duration_unit: "t",
          amount: currentStake,
          basis: "stake",
        })

        const result = await api.buyContract(proposal.id, proposal.ask_price)

        const newTrade: TradeHistory = {
          id: result.contract_id,
          type: direction,
          amount: currentStake,
          profit: 0,
          status: "open",
        }

        setTrades((prev) => [newTrade, ...prev.slice(0, 49)])

        const { balance: newBalance } = await api.getBalance()
        setBalance(newBalance)

        const checkResult = setInterval(async () => {
          try {
            const update = await api.getContractUpdate(result.contract_id)
            if (update.status !== "open") {
              clearInterval(checkResult)

              setTrades((prev) =>
                prev.map((t) =>
                  t.id === result.contract_id ? { ...t, profit: update.profit, status: update.status } : t,
                ),
              )

              const newProfit = totalProfitRef.current + update.profit
              totalProfitRef.current = newProfit
              setTotalProfit(newProfit)

              if (update.status === "won") {
                martingaleLevelRef.current = 0
                setMartingaleLevel(0)
              } else if (martingale) {
                martingaleLevelRef.current = Math.min(martingaleLevelRef.current + 1, 5)
                setMartingaleLevel(martingaleLevelRef.current)
              }

              setTrades((prev) => {
                const completed = prev.filter((t) => t.status !== "open")
                const wins = completed.filter((t) => t.status === "won").length
                setWinRate(completed.length > 0 ? (wins / completed.length) * 100 : 0)
                return prev
              })

              const { balance: finalBalance } = await api.getBalance()
              setBalance(finalBalance)
              setIsTrading(false)
            }
          } catch {
            clearInterval(checkResult)
            setIsTrading(false)
          }
        }, 1000)
      } catch (error) {
        console.error("Trade error:", error)
        setIsTrading(false)
      }
    },
    [api, stake, symbol, duration, martingale, balance, targetProfit, stopLoss, isTrading],
  )

  const toggleAutoTrading = () => {
    const newState = !isAutoRunning
    setIsAutoRunning(newState)
    autoRunningRef.current = newState
    if (!newState) {
      martingaleLevelRef.current = 0
      setMartingaleLevel(0)
    }
  }

  // Calculate tick movements
  const tickMovements = ticks.slice(-20).map((tick, i, arr) => {
    if (i === 0) return { tick, direction: "neutral" as const }
    return {
      tick,
      direction:
        tick.quote > arr[i - 1].quote
          ? ("up" as const)
          : tick.quote < arr[i - 1].quote
            ? ("down" as const)
            : ("neutral" as const),
    }
  })

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-lg font-bold">Tick Picker Strategy</h1>
              <p className="text-xs text-muted-foreground">Pattern Analysis Auto Trading</p>
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
        {/* Auto Trading Status */}
        <Card className={`mb-4 ${isAutoRunning ? "border-green-500/50 bg-green-500/10" : ""}`}>
          <CardContent className="py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isAutoRunning && <div className="h-3 w-3 bg-green-500 rounded-full animate-pulse"></div>}
                <span className={`font-semibold ${isAutoRunning ? "text-green-400" : "text-muted-foreground"}`}>
                  {isAutoRunning ? "Auto Trading Active" : "Auto Trading Stopped"}
                </span>
                {isTrading && <Badge className="bg-yellow-600">Trading...</Badge>}
                {martingaleLevel > 0 && <Badge className="bg-orange-600">M{martingaleLevel}</Badge>}
              </div>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={() => setShowSettings(!showSettings)}>
                  <Settings2 className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  onClick={toggleAutoTrading}
                  className={isAutoRunning ? "bg-red-600 hover:bg-red-700" : "bg-green-600 hover:bg-green-700"}
                >
                  {isAutoRunning ? (
                    <>
                      <Square className="h-4 w-4 mr-2" />
                      STOP
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      START
                    </>
                  )}
                </Button>
              </div>
            </div>

            {showSettings && (
              <div className="mt-4 pt-4 border-t border-border grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">Stake ($)</Label>
                  <Input
                    type="number"
                    value={stake}
                    onChange={(e) => setStake(Number(e.target.value) || 1)}
                    className="bg-input"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Duration (Ticks)</Label>
                  <Select value={duration.toString()} onValueChange={(v) => setDuration(Number(v))}>
                    <SelectTrigger className="bg-input">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[1, 3, 5, 7, 10].map((d) => (
                        <SelectItem key={d} value={d.toString()}>
                          {d} ticks
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Target ($)</Label>
                  <Input
                    type="number"
                    value={targetProfit}
                    onChange={(e) => setTargetProfit(Number(e.target.value) || 10)}
                    className="bg-input"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Stop Loss ($)</Label>
                  <Input
                    type="number"
                    value={stopLoss}
                    onChange={(e) => setStopLoss(Number(e.target.value) || 20)}
                    className="bg-input"
                  />
                </div>
                <div className="flex items-center justify-between p-2 bg-input rounded">
                  <Label className="text-xs">Martingale</Label>
                  <Switch checked={martingale} onCheckedChange={setMartingale} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            {/* Symbol & Price */}
            <div className="flex items-center gap-4">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[200px] bg-card">
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
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-mono font-bold">{ticks[ticks.length - 1]?.quote.toFixed(5)}</span>
                  {ticks.length > 1 &&
                    (ticks[ticks.length - 1].quote > ticks[ticks.length - 2].quote ? (
                      <TrendingUp className="h-5 w-5 text-green-500" />
                    ) : ticks[ticks.length - 1].quote < ticks[ticks.length - 2].quote ? (
                      <TrendingDown className="h-5 w-5 text-red-500" />
                    ) : (
                      <Minus className="h-5 w-5 text-gray-500" />
                    ))}
                </div>
              )}
            </div>

            {/* Chart */}
            <Card className="bg-card">
              <CardContent className="p-4">
                <TradingChart
                  ticks={ticks}
                  height={300}
                  lineColor={pattern?.prediction === "rise" ? "#22c55e" : "#ef4444"}
                />
              </CardContent>
            </Card>

            {/* Tick Movement Visualization */}
            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Recent Tick Movements</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex gap-1 overflow-x-auto pb-2">
                  {tickMovements.map((item, i) => (
                    <div
                      key={i}
                      className={`flex-shrink-0 w-8 h-12 rounded flex items-center justify-center ${
                        item.direction === "up"
                          ? "bg-green-500/20"
                          : item.direction === "down"
                            ? "bg-red-500/20"
                            : "bg-gray-500/20"
                      }`}
                    >
                      {item.direction === "up" ? (
                        <ArrowUp className="h-4 w-4 text-green-500" />
                      ) : item.direction === "down" ? (
                        <ArrowDown className="h-4 w-4 text-red-500" />
                      ) : (
                        <Minus className="h-4 w-4 text-gray-500" />
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Pattern Analysis */}
            {pattern && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card className="bg-card">
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground mb-1">Trend</div>
                    <Badge
                      className={
                        pattern.trend === "up"
                          ? "bg-green-600"
                          : pattern.trend === "down"
                            ? "bg-red-600"
                            : "bg-gray-600"
                      }
                    >
                      {pattern.trend.toUpperCase()}
                    </Badge>
                  </CardContent>
                </Card>

                <Card className="bg-card">
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground mb-1">Strength</div>
                    <div className="text-xl font-bold">{pattern.strength.toFixed(0)}%</div>
                  </CardContent>
                </Card>

                <Card className="bg-card">
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground mb-1">Consecutive</div>
                    <div className="text-xl font-bold">{pattern.consecutive}</div>
                  </CardContent>
                </Card>

                <Card className="border-primary/50 bg-primary/5">
                  <CardContent className="p-3">
                    <div className="text-xs text-muted-foreground mb-1">Signal</div>
                    <div className="flex items-center gap-2">
                      <Badge className={pattern.prediction === "rise" ? "bg-green-600" : "bg-red-600"}>
                        {pattern.prediction.toUpperCase()}
                      </Badge>
                      <span className="text-sm font-semibold">{pattern.confidence}%</span>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>

          {/* Stats & History */}
          <div className="space-y-4">
            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Session Stats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Total Trades</span>
                  <span className="font-semibold">{trades.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Win Rate</span>
                  <span className={`font-semibold ${winRate >= 50 ? "text-green-500" : "text-red-500"}`}>
                    {winRate.toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Profit/Loss</span>
                  <span className={`font-semibold ${totalProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {totalProfit >= 0 ? "+" : ""}
                    {totalProfit.toFixed(2)}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="bg-card">
              <CardHeader className="py-3">
                <CardTitle className="text-sm">Trade History</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[300px] overflow-y-auto">
                  {trades.map((trade) => (
                    <div key={trade.id} className="flex items-center justify-between p-2 border-t border-border">
                      <Badge
                        className={
                          trade.status === "won"
                            ? "bg-green-600"
                            : trade.status === "lost"
                              ? "bg-red-600"
                              : "bg-yellow-600"
                        }
                      >
                        {trade.type.toUpperCase()}
                      </Badge>
                      <span className="text-sm">${trade.amount.toFixed(2)}</span>
                      <span className={trade.profit >= 0 ? "text-green-500" : "text-red-500"}>
                        {trade.profit >= 0 ? "+" : ""}
                        {trade.profit.toFixed(2)}
                      </span>
                    </div>
                  ))}
                  {trades.length === 0 && <p className="text-center text-muted-foreground p-4">No trades yet</p>}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
