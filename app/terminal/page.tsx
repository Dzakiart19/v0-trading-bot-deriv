"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { TradingChart } from "@/components/trading-chart"
import { type DerivAPI, type TickData, createDerivAPI } from "@/lib/deriv-api"
import { RSI, EMA, MACD, analyzeTickPattern } from "@/lib/indicators"
import {
  ArrowLeft,
  Wifi,
  WifiOff,
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  Target,
  Square,
  Play,
  Settings2,
} from "lucide-react"

const SYMBOLS = [
  { value: "R_10", label: "Volatility 10" },
  { value: "R_25", label: "Volatility 25" },
  { value: "R_50", label: "Volatility 50" },
  { value: "R_75", label: "Volatility 75" },
  { value: "R_100", label: "Volatility 100" },
  { value: "1HZ10V", label: "Volatility 10 (1s)" },
  { value: "1HZ25V", label: "Volatility 25 (1s)" },
  { value: "1HZ50V", label: "Volatility 50 (1s)" },
  { value: "1HZ75V", label: "Volatility 75 (1s)" },
  { value: "1HZ100V", label: "Volatility 100 (1s)" },
]

interface TradeHistory {
  id: number
  type: string
  amount: number
  profit: number
  status: "won" | "lost" | "open"
  time: Date
}

interface Analysis {
  rsi: number
  ema9: number
  ema21: number
  macdSignal: "buy" | "sell" | "neutral"
  trend: "up" | "down" | "sideways"
  confidence: number
  prediction: "rise" | "fall"
}

export default function TerminalPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [api, setApi] = useState<DerivAPI | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [symbol, setSymbol] = useState("R_100")
  const [ticks, setTicks] = useState<TickData[]>([])
  const [balance, setBalance] = useState(0)
  const [currency, setCurrency] = useState("USD")
  const [trades, setTrades] = useState<TradeHistory[]>([])
  const [totalProfit, setTotalProfit] = useState(0)
  const [winRate, setWinRate] = useState(0)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)

  const [isAutoRunning, setIsAutoRunning] = useState(false)
  const [stake, setStake] = useState(1)
  const [targetProfit, setTargetProfit] = useState(10)
  const [stopLoss, setStopLoss] = useState(20)
  const [martingale, setMartingale] = useState(true)
  const [martingaleLevel, setMartingaleLevel] = useState(0)
  const [showSettings, setShowSettings] = useState(false)
  const [isTrading, setIsTrading] = useState(false)

  const autoRunningRef = useRef(false)
  const martingaleLevelRef = useRef(0)
  const totalProfitRef = useRef(0)

  // Initialize API and auto-start if param is set
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

  // Change symbol
  useEffect(() => {
    if (!api || !isConnected) return

    api.unsubscribeTicks(symbol).then(() => {
      api.getTickHistory(symbol, 100).then(setTicks)
      api.subscribeTicks(symbol, (tick) => {
        setTicks((prev) => [...prev.slice(-99), tick])
      })
    })
  }, [symbol, api, isConnected])

  useEffect(() => {
    if (ticks.length < 30) return

    const prices = ticks.map((t) => t.quote)
    const rsiValues = RSI(prices, 14)
    const ema9Values = EMA(prices, 9)
    const ema21Values = EMA(prices, 21)
    const macdResult = MACD(prices)
    const pattern = analyzeTickPattern(prices.slice(-20))

    const currentRSI = rsiValues[rsiValues.length - 1] || 50
    const currentEMA9 = ema9Values[ema9Values.length - 1] || 0
    const currentEMA21 = ema21Values[ema21Values.length - 1] || 0
    const currentMACD = macdResult.histogram[macdResult.histogram.length - 1] || 0

    let bullishSignals = 0
    let bearishSignals = 0

    if (currentRSI < 30) bullishSignals += 2
    else if (currentRSI < 40) bullishSignals += 1
    else if (currentRSI > 70) bearishSignals += 2
    else if (currentRSI > 60) bearishSignals += 1

    if (currentEMA9 > currentEMA21) bullishSignals += 1
    else if (currentEMA9 < currentEMA21) bearishSignals += 1

    if (currentMACD > 0) bullishSignals += 1
    else bearishSignals += 1

    if (pattern.trend === "up") bullishSignals += 1
    else if (pattern.trend === "down") bearishSignals += 1

    const totalSignals = bullishSignals + bearishSignals
    const confidence = Math.round((Math.max(bullishSignals, bearishSignals) / totalSignals) * 100)
    const prediction = bullishSignals > bearishSignals ? "rise" : "fall"

    const newAnalysis = {
      rsi: currentRSI,
      ema9: currentEMA9,
      ema21: currentEMA21,
      macdSignal: currentMACD > 0 ? ("buy" as const) : currentMACD < 0 ? ("sell" as const) : ("neutral" as const),
      trend: pattern.trend as "up" | "down" | "sideways",
      confidence: Math.min(confidence, 95),
      prediction: prediction as "rise" | "fall",
    }

    setAnalysis(newAnalysis)

    if (autoRunningRef.current && !isTrading && confidence >= 70) {
      executeTrade(prediction as "rise" | "fall")
    }
  }, [ticks])

  const executeTrade = useCallback(
    async (direction: "rise" | "fall") => {
      if (!api || isTrading) return

      // Check profit/loss limits
      if (totalProfitRef.current >= targetProfit) {
        setIsAutoRunning(false)
        autoRunningRef.current = false
        return
      }
      if (totalProfitRef.current <= -stopLoss) {
        setIsAutoRunning(false)
        autoRunningRef.current = false
        return
      }

      setIsTrading(true)

      try {
        // Calculate stake with martingale
        let currentStake = stake
        if (martingale && martingaleLevelRef.current > 0) {
          currentStake = stake * Math.pow(2, martingaleLevelRef.current)
        }
        currentStake = Math.min(currentStake, balance * 0.2)

        const proposal = await api.getProposal({
          contract_type: direction === "rise" ? "CALL" : "PUT",
          symbol,
          duration: 5,
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
          time: new Date(),
        }

        setTrades((prev) => [newTrade, ...prev.slice(0, 49)])

        const { balance: newBalance } = await api.getBalance()
        setBalance(newBalance)

        // Monitor contract result
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

              // Update martingale level
              if (update.status === "won") {
                martingaleLevelRef.current = 0
                setMartingaleLevel(0)
              } else if (martingale) {
                martingaleLevelRef.current = Math.min(martingaleLevelRef.current + 1, 5)
                setMartingaleLevel(martingaleLevelRef.current)
              }

              // Update stats
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
          } catch (e) {
            clearInterval(checkResult)
            setIsTrading(false)
          }
        }, 1000)
      } catch (error) {
        console.error("Trade error:", error)
        setIsTrading(false)
      }
    },
    [api, stake, symbol, martingale, balance, targetProfit, stopLoss, isTrading],
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

  return (
    <div className="min-h-screen bg-[#0d1117] text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-[#161b22] sticky top-0 z-10">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => router.push("/")}
              className="text-gray-400 hover:text-white hover:bg-gray-800"
            >
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-lg font-bold">Terminal Strategy</h1>
              <p className="text-xs text-gray-400">Smart Analysis Auto Trading</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              {isConnected ? <Wifi className="h-4 w-4 text-green-500" /> : <WifiOff className="h-4 w-4 text-red-500" />}
              <span className="text-sm text-gray-400">{isConnected ? "Connected" : "Disconnected"}</span>
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
        {/* Auto Trading Status Bar */}
        <Card
          className={`mb-4 border ${isAutoRunning ? "border-green-500/50 bg-green-500/10" : "border-gray-700 bg-[#161b22]"}`}
        >
          <CardContent className="py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isAutoRunning && <div className="h-3 w-3 bg-green-500 rounded-full animate-pulse"></div>}
                <span className={`font-semibold ${isAutoRunning ? "text-green-400" : "text-gray-400"}`}>
                  {isAutoRunning ? "Auto Trading Active" : "Auto Trading Stopped"}
                </span>
                {isTrading && <Badge className="bg-yellow-600">Trading...</Badge>}
                {martingaleLevel > 0 && <Badge className="bg-orange-600">M{martingaleLevel}</Badge>}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowSettings(!showSettings)}
                  className="text-gray-400 hover:text-white"
                >
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

            {/* Settings Panel */}
            {showSettings && (
              <div className="mt-4 pt-4 border-t border-gray-700 grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs text-gray-400">Stake ($)</Label>
                  <Input
                    type="number"
                    value={stake}
                    onChange={(e) => setStake(Number(e.target.value) || 1)}
                    className="bg-gray-800 border-gray-700 text-white"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-gray-400">Target Profit ($)</Label>
                  <Input
                    type="number"
                    value={targetProfit}
                    onChange={(e) => setTargetProfit(Number(e.target.value) || 10)}
                    className="bg-gray-800 border-gray-700 text-white"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-gray-400">Stop Loss ($)</Label>
                  <Input
                    type="number"
                    value={stopLoss}
                    onChange={(e) => setStopLoss(Number(e.target.value) || 20)}
                    className="bg-gray-800 border-gray-700 text-white"
                  />
                </div>
                <div className="flex items-center justify-between p-2 bg-gray-800 rounded">
                  <Label className="text-xs text-gray-400">Martingale</Label>
                  <Switch checked={martingale} onCheckedChange={setMartingale} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Chart Section */}
          <div className="lg:col-span-2 space-y-4">
            {/* Symbol Selector */}
            <div className="flex items-center gap-4">
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[200px] bg-[#161b22] border-gray-700 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#161b22] border-gray-700">
                  {SYMBOLS.map((s) => (
                    <SelectItem key={s.value} value={s.value} className="text-white hover:bg-gray-800">
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
                    ) : (
                      <TrendingDown className="h-5 w-5 text-red-500" />
                    ))}
                </div>
              )}
            </div>

            {/* Chart */}
            <Card className="bg-[#161b22] border-gray-800">
              <CardContent className="p-4">
                <TradingChart
                  ticks={ticks}
                  height={350}
                  lineColor={analysis?.prediction === "rise" ? "#22c55e" : "#ef4444"}
                />
              </CardContent>
            </Card>

            {/* Analysis Panel */}
            {analysis && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card className="bg-[#161b22] border-gray-800">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2 text-gray-400 mb-1">
                      <Activity className="h-4 w-4" />
                      <span className="text-xs">RSI(14)</span>
                    </div>
                    <div
                      className={`text-xl font-bold ${
                        analysis.rsi < 30 ? "text-green-500" : analysis.rsi > 70 ? "text-red-500" : "text-white"
                      }`}
                    >
                      {analysis.rsi.toFixed(1)}
                    </div>
                  </CardContent>
                </Card>

                <Card className="bg-[#161b22] border-gray-800">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2 text-gray-400 mb-1">
                      <BarChart3 className="h-4 w-4" />
                      <span className="text-xs">MACD</span>
                    </div>
                    <Badge
                      className={
                        analysis.macdSignal === "buy"
                          ? "bg-green-600"
                          : analysis.macdSignal === "sell"
                            ? "bg-red-600"
                            : "bg-gray-600"
                      }
                    >
                      {analysis.macdSignal.toUpperCase()}
                    </Badge>
                  </CardContent>
                </Card>

                <Card className="bg-[#161b22] border-gray-800">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2 text-gray-400 mb-1">
                      <TrendingUp className="h-4 w-4" />
                      <span className="text-xs">Trend</span>
                    </div>
                    <Badge
                      className={
                        analysis.trend === "up"
                          ? "bg-green-600"
                          : analysis.trend === "down"
                            ? "bg-red-600"
                            : "bg-gray-600"
                      }
                    >
                      {analysis.trend.toUpperCase()}
                    </Badge>
                  </CardContent>
                </Card>

                <Card className="bg-[#161b22] border-gray-800">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-2 text-gray-400 mb-1">
                      <Target className="h-4 w-4" />
                      <span className="text-xs">Signal</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge className={analysis.prediction === "rise" ? "bg-green-600" : "bg-red-600"}>
                        {analysis.prediction.toUpperCase()}
                      </Badge>
                      <span className="text-sm font-semibold">{analysis.confidence}%</span>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>

          {/* Stats & History */}
          <div className="space-y-4">
            {/* Session Stats */}
            <Card className="bg-[#161b22] border-gray-800">
              <CardHeader className="py-3">
                <CardTitle className="text-sm text-white">Session Stats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total Trades</span>
                  <span className="font-semibold">{trades.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Win Rate</span>
                  <span className={`font-semibold ${winRate >= 50 ? "text-green-500" : "text-red-500"}`}>
                    {winRate.toFixed(1)}%
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Profit/Loss</span>
                  <span className={`font-semibold ${totalProfit >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {totalProfit >= 0 ? "+" : ""}
                    {totalProfit.toFixed(2)} {currency}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Martingale Level</span>
                  <span className="font-semibold">{martingaleLevel}/5</span>
                </div>
              </CardContent>
            </Card>

            {/* Trade History */}
            <Card className="bg-[#161b22] border-gray-800">
              <CardHeader className="py-3">
                <CardTitle className="text-sm text-white">Trade History</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[300px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-800/50 sticky top-0">
                      <tr>
                        <th className="text-left p-2 text-gray-400">Type</th>
                        <th className="text-right p-2 text-gray-400">Amount</th>
                        <th className="text-right p-2 text-gray-400">Profit</th>
                        <th className="text-center p-2 text-gray-400">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((trade) => (
                        <tr key={trade.id} className="border-t border-gray-800">
                          <td className="p-2">
                            <Badge className={`text-xs ${trade.type === "rise" ? "bg-green-600" : "bg-red-600"}`}>
                              {trade.type.toUpperCase()}
                            </Badge>
                          </td>
                          <td className="text-right p-2 text-gray-300">${trade.amount.toFixed(2)}</td>
                          <td className={`text-right p-2 ${trade.profit >= 0 ? "text-green-500" : "text-red-500"}`}>
                            {trade.profit >= 0 ? "+" : ""}
                            {trade.profit.toFixed(2)}
                          </td>
                          <td className="text-center p-2">
                            <Badge
                              className={`text-xs ${
                                trade.status === "won"
                                  ? "bg-green-600"
                                  : trade.status === "lost"
                                    ? "bg-red-600"
                                    : "bg-yellow-600"
                              }`}
                            >
                              {trade.status.toUpperCase()}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                      {trades.length === 0 && (
                        <tr>
                          <td colSpan={4} className="text-center p-4 text-gray-500">
                            No trades yet - Auto trading will start when signal detected
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </div>
  )
}
