#pragma once
#include "common.h"

namespace iohkx
{
	class AnimationDecoder
	{
	public:
		AnimationDecoder();
		~AnimationDecoder();

		hkRefPtr<hkaAnimationContainer> compress();
		void decompress(hkaAnimationContainer* animCtnr, 
			const std::vector<Skeleton*>& skeletons);

		AnimationData& get() { return m_data; }
		const AnimationData& get() const { return m_data; }

		void setFrameRate(int frameRate) { m_frameRate = frameRate; }
		int getFrameRate() const { return m_frameRate; }

		//Spline compression tolerance presets
		enum TolerancePreset
		{
			//Tolerances matched to the quantization error of the
			//THREECOMP40 rotation format (~1e-4)
			TOLERANCE_PRECISE,
			//Tolerances used by versions prior to 0.2.0
			//(0.004 for translation/scale/float, 0.001 for rotation)
			TOLERANCE_LEGACY,
		};

		void setTolerance(TolerancePreset preset) { m_tolerance = preset; }
		TolerancePreset getTolerance() const { return m_tolerance; }

	private:
		void removeDuplicateKeys();
		void preProcess();

	private:
		AnimationData m_data;
		int m_frameRate;
		TolerancePreset m_tolerance{ TOLERANCE_PRECISE };
	};
}
