"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ArrowUp, ArrowDown, Play, Square, Settings2 } from "lucide-react"

interface TradePanelProps {
  balance: number
  currency: string
  onTrade: (params: TradeParams) => void
  onStartAuto: (config: AutoConfig) => void
  onStopAuto: () => void
  isAutoRunning: boolean
  prediction?: {
    direction: "rise" | "fall" | "even" | "odd" | "match" | "differ"
    confidence: number
  }
}

export interface TradeParams {
  type: "rise" | "fall" | "even" | "odd" | "match" | "differ"
  amount: number
  duration: number
  durationUnit: "t" | "s" | "m"
  barrier?: number
}

export interface AutoConfig {
  initialStake: number
  targetProfit: number
  stopLoss: number
  martingale: boolean
  martingaleMultiplier: number
  maxMartingaleLevel: number
}

export function TradePanel({
  balance,
  currency,
  onTrade,
  onStartAuto,
  onStopAuto,
  isAutoRunning,
  prediction,
}: TradePanelProps) {
  const [stake, setStake] = useState(1)
  const [duration, setDuration] = useState(5)
  const [durationUnit, setDurationUnit] = useState<"t" | "s" | "m">("t")
  const [showAutoConfig, setShowAutoConfig] = useState(false)

  // Auto config
  const [targetProfit, setTargetProfit] = useState(10)
  const [stopLoss, setStopLoss] = useState(20)
  const [martingale, setMartingale] = useState(true)
  const [martingaleMultiplier, setMartingaleMultiplier] = useState(2.0)
  const [maxMartingale, setMaxMartingale] = useState(5)

  const handleManualTrade = (type: TradeParams["type"]) => {
    onTrade({
      type,
      amount: stake,
      duration,
      durationUnit,
    })
  }

  const handleStartAuto = () => {
    onStartAuto({
      initialStake: stake,
      targetProfit,
      stopLoss,
      martingale,
      martingaleMultiplier,
      maxMartingaleLevel: maxMartingale,
    })
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Trade Control</CardTitle>
          <Button variant="ghost" size="sm" onClick={() => setShowAutoConfig(!showAutoConfig)}>
            <Settings2 className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Prediction Display */}
        {prediction && (
          <div className="p-3 rounded-lg bg-primary/10 border border-primary/20">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Signal</span>
              <div className="flex items-center gap-2">
                <Badge variant={prediction.confidence >= 80 ? "default" : "secondary"}>
                  {prediction.direction.toUpperCase()}
                </Badge>
                <span className="text-sm font-semibold">{prediction.confidence}%</span>
              </div>
            </div>
          </div>
        )}

        {/* Stake & Duration */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label className="text-xs">Stake ({currency})</Label>
            <Input
              type="number"
              value={stake}
              onChange={(e) => setStake(Number.parseFloat(e.target.value) || 0)}
              min={0.35}
              step={0.1}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-xs">Duration</Label>
            <div className="flex gap-1">
              <Input
                type="number"
                value={duration}
                onChange={(e) => setDuration(Number.parseInt(e.target.value) || 1)}
                min={1}
                className="w-16"
              />
              <Select value={durationUnit} onValueChange={(v) => setDurationUnit(v as "t" | "s" | "m")}>
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="t">Ticks</SelectItem>
                  <SelectItem value="s">Secs</SelectItem>
                  <SelectItem value="m">Mins</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        {/* Quick Stakes */}
        <div className="flex gap-2">
          {[1, 5, 10, 25].map((val) => (
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

        {/* Manual Trade Buttons */}
        <div className="grid grid-cols-2 gap-3">
          <Button
            size="lg"
            className="bg-green-600 hover:bg-green-700 h-14"
            onClick={() => handleManualTrade("rise")}
            disabled={isAutoRunning}
          >
            <ArrowUp className="h-5 w-5 mr-2" />
            RISE
          </Button>
          <Button
            size="lg"
            className="bg-red-600 hover:bg-red-700 h-14"
            onClick={() => handleManualTrade("fall")}
            disabled={isAutoRunning}
          >
            <ArrowDown className="h-5 w-5 mr-2" />
            FALL
          </Button>
        </div>

        {/* Auto Config Panel */}
        {showAutoConfig && (
          <div className="space-y-3 p-3 bg-muted/50 rounded-lg">
            <h4 className="font-semibold text-sm">Auto Trading Config</h4>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Target Profit ($)</Label>
                <Input
                  type="number"
                  value={targetProfit}
                  onChange={(e) => setTargetProfit(Number.parseFloat(e.target.value) || 0)}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Stop Loss ($)</Label>
                <Input
                  type="number"
                  value={stopLoss}
                  onChange={(e) => setStopLoss(Number.parseFloat(e.target.value) || 0)}
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <Label className="text-sm">Martingale</Label>
              <Switch checked={martingale} onCheckedChange={setMartingale} />
            </div>

            {martingale && (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Multiplier</Label>
                  <Input
                    type="number"
                    value={martingaleMultiplier}
                    onChange={(e) => setMartingaleMultiplier(Number.parseFloat(e.target.value) || 2)}
                    step={0.1}
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Max Level</Label>
                  <Input
                    type="number"
                    value={maxMartingale}
                    onChange={(e) => setMaxMartingale(Number.parseInt(e.target.value) || 5)}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Auto Start/Stop Button */}
        <Button
          size="lg"
          className={`w-full h-12 ${isAutoRunning ? "bg-orange-600 hover:bg-orange-700" : "bg-blue-600 hover:bg-blue-700"}`}
          onClick={isAutoRunning ? onStopAuto : handleStartAuto}
        >
          {isAutoRunning ? (
            <>
              <Square className="h-5 w-5 mr-2" />
              STOP AUTO
            </>
          ) : (
            <>
              <Play className="h-5 w-5 mr-2" />
              START AUTO
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}
